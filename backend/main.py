"""
FastAPI backend for WhoIsOnMySide.
Endpoints:
  GET  /figures                   – list all figures with their verdicts
  GET  /figures/{id}/chunks       – paginated chunks for a figure
  GET  /figures/{id}/verdict      – aggregated stance per axis
  POST /annotations               – save a human label
  POST /predict                   – run LLM judge on a chunk (or all unlabeled)
  GET  /sanity                    – Ambedkar sanity check
"""

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(__file__).parent.parent / "db" / "whoismyside.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"
MODEL = "claude-haiku-4-5"
PROMPT_VERSION = "v1"

AXES = ["untouchability", "varna_hierarchy", "endogamy", "temple_entry", "general_caste",
        "communalism", "hindu_nationalism"]
STANCE_VALUES = {"pro": 1.0, "anti": -1.0, "mixed": 0.0, "not_about_caste": None}
ROLE_WEIGHT = {"author_asserted": 2.0, "quoted_other": 1.0, "describing": 0.5, "ambiguous": 1.0}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    yield

app = FastAPI(title="WhoIsOnMySide", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AnnotationIn(BaseModel):
    chunk_id: int
    speaker_role: str
    axis: str
    stance: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    notes: Optional[str] = None


class PredictRequest(BaseModel):
    chunk_id: Optional[int] = None  # None → predict all unlabeled chunks
    axis: str = "general_caste"


# ---------------------------------------------------------------------------
# Routes: figures + verdicts
# ---------------------------------------------------------------------------

@app.get("/figures")
def list_figures():
    conn = get_conn()
    figures = conn.execute("SELECT * FROM figures ORDER BY name").fetchall()
    result = []
    for f in figures:
        verdicts = conn.execute(
            """
            SELECT axis, stance, score FROM verdicts
            WHERE figure_id = ?
              AND (axis, computed_at) IN (
                  SELECT axis, MAX(computed_at) FROM verdicts WHERE figure_id = ? GROUP BY axis
              )
            ORDER BY axis
            """,
            (f["id"], f["id"]),
        ).fetchall()
        result.append({**dict(f), "verdicts": [dict(v) for v in verdicts]})
    conn.close()
    return result


@app.get("/figures/{figure_id}")
def get_figure(figure_id: int):
    conn = get_conn()
    f = conn.execute("SELECT * FROM figures WHERE id = ?", (figure_id,)).fetchone()
    if not f:
        raise HTTPException(404, "Figure not found")
    works = conn.execute(
        "SELECT id, title, year_written, source_url FROM works WHERE figure_id = ?",
        (figure_id,),
    ).fetchall()
    verdicts = conn.execute(
        "SELECT * FROM verdicts WHERE figure_id = ? ORDER BY axis",
        (figure_id,),
    ).fetchall()
    conn.close()
    return {**dict(f), "works": [dict(w) for w in works], "verdicts": [dict(v) for v in verdicts]}


@app.get("/figures/{figure_id}/chunks")
def get_chunks(figure_id: int, page: int = 0, per_page: int = 20):
    conn = get_conn()
    offset = page * per_page
    chunks = conn.execute(
        """
        SELECT c.id, c.ord, c.text_raw, c.text_masked,
               w.title AS work_title
        FROM chunks c
        JOIN works w ON w.id = c.work_id
        WHERE w.figure_id = ? AND c.readable = 1
        ORDER BY w.id, c.ord
        LIMIT ? OFFSET ?
        """,
        (figure_id, per_page, offset),
    ).fetchall()

    # attach any existing annotations/predictions per chunk
    result = []
    for ch in chunks:
        anns = conn.execute(
            "SELECT axis, stance, speaker_role, confidence FROM annotations WHERE chunk_id = ?",
            (ch["id"],),
        ).fetchall()
        preds = conn.execute(
            "SELECT axis, stance, speaker_role, score FROM predictions WHERE chunk_id = ?",
            (ch["id"],),
        ).fetchall()
        result.append({
            **dict(ch),
            "annotations": [dict(a) for a in anns],
            "predictions": [dict(p) for p in preds],
        })
    conn.close()
    return {"chunks": result, "page": page, "per_page": per_page}


# ---------------------------------------------------------------------------
# Route: human annotation
# ---------------------------------------------------------------------------

@app.post("/annotations")
def save_annotation(ann: AnnotationIn):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO annotations(chunk_id, annotator, speaker_role, axis, stance, confidence, notes)
        VALUES (?, 'human', ?, ?, ?, ?, ?)
        ON CONFLICT(chunk_id, annotator, axis) DO UPDATE SET
            speaker_role = excluded.speaker_role,
            stance       = excluded.stance,
            confidence   = excluded.confidence,
            notes        = excluded.notes,
            created_at   = datetime('now')
        """,
        (ann.chunk_id, ann.speaker_role, ann.axis, ann.stance, ann.confidence, ann.notes),
    )
    conn.commit()
    _recompute_verdict_for_chunk(conn, ann.chunk_id)
    conn.close()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Route: LLM prediction
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """\
You are an expert on the history of the Indian caste system.
Classify the following passage on the axis: {axis}.

Axis definitions:
- untouchability: mentions of untouchable communities, discrimination, pollution taboos
- varna_hierarchy: four-varna (Brahmin/Kshatriya/Vaishya/Shudra) ordering as divinely ordained
- endogamy: inter-caste marriage restriction
- temple_entry: right of lower-caste people to enter Hindu temples
- general_caste: caste system overall

Return ONLY a JSON object with these keys:
{{
  "speaker_role": "author_asserted" | "quoted_other" | "describing" | "ambiguous",
  "stance": "pro" | "anti" | "mixed" | "not_about_caste",
  "score": <float 0-1, confidence>,
  "reasoning": "<one sentence>"
}}

Passage:
\"\"\"
{text}
\"\"\"
"""


def _llm_classify(chunk_text: str, axis: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = CLASSIFY_PROMPT.format(axis=axis, text=chunk_text[:3000])
    msg = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip markdown code fences if present
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


@app.post("/predict")
def predict(req: PredictRequest):
    conn = get_conn()
    if req.chunk_id is not None:
        chunks = conn.execute(
            "SELECT id, text_masked FROM chunks WHERE id = ? AND readable = 1", (req.chunk_id,)
        ).fetchall()
    else:
        # All readable chunks that have no prediction yet for this axis
        chunks = conn.execute(
            """
            SELECT c.id, c.text_masked FROM chunks c
            WHERE c.readable = 1
              AND NOT EXISTS (
                SELECT 1 FROM predictions p
                WHERE p.chunk_id = c.id AND p.axis = ? AND p.model_name = ?
              )
            LIMIT 50
            """,
            (req.axis, MODEL),
        ).fetchall()

    results = []
    for ch in chunks:
        text = ch["text_masked"] or ""
        if not text.strip():
            continue
        try:
            pred = _llm_classify(text, req.axis)
        except Exception as e:
            results.append({"chunk_id": ch["id"], "error": str(e)})
            continue

        conn.execute(
            """
            INSERT INTO predictions
                (chunk_id, model_name, prompt_version, speaker_role, axis, stance, score, raw_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ch["id"], MODEL, PROMPT_VERSION,
                pred.get("speaker_role", "ambiguous"),
                req.axis,
                pred.get("stance", "not_about_caste"),
                pred.get("score", 0.0),
                json.dumps(pred),
            ),
        )
        conn.commit()
        _recompute_verdict_for_chunk(conn, ch["id"])
        results.append({"chunk_id": ch["id"], "prediction": pred})

    conn.close()
    return {"results": results}


# ---------------------------------------------------------------------------
# Verdict recomputation (called after each annotation/prediction write)
# ---------------------------------------------------------------------------

def _recompute_verdict_for_chunk(conn: sqlite3.Connection, chunk_id: int) -> None:
    """Recompute verdicts for the figure owning this chunk, for all axes."""
    row = conn.execute(
        "SELECT w.figure_id FROM chunks c JOIN works w ON w.id = c.work_id WHERE c.id = ?",
        (chunk_id,),
    ).fetchone()
    if not row:
        return
    _recompute_verdicts(conn, row["figure_id"])


def _recompute_verdicts(conn: sqlite3.Connection, figure_id: int) -> None:
    for axis in AXES:
        rows = conn.execute(
            """
            SELECT p.stance, p.speaker_role, p.score, p.chunk_id
            FROM predictions p
            JOIN chunks c ON c.id = p.chunk_id
            JOIN works w ON w.id = c.work_id
            WHERE w.figure_id = ? AND p.axis = ? AND p.model_name = ?
            """,
            (figure_id, axis, MODEL),
        ).fetchall()

        scored = [r for r in rows if STANCE_VALUES.get(r["stance"]) is not None]
        if not scored:
            continue

        total_weight = 0.0
        weighted_sum = 0.0
        chunk_ids = []
        for r in scored:
            w = ROLE_WEIGHT.get(r["speaker_role"], 1.0)
            weighted_sum += STANCE_VALUES[r["stance"]] * w * (r["score"] or 1.0)
            total_weight += w
            chunk_ids.append(r["chunk_id"])

        score = weighted_sum / total_weight if total_weight else 0.0
        stance = "anti" if score < -0.2 else "pro" if score > 0.2 else "mixed"

        conn.execute(
            """
            INSERT INTO verdicts(figure_id, axis, stance, score, method_version, evidence_chunk_ids)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(figure_id, axis, method_version) DO UPDATE SET
                stance = excluded.stance,
                score  = excluded.score,
                evidence_chunk_ids = excluded.evidence_chunk_ids,
                computed_at = datetime('now')
            """,
            (figure_id, axis, stance, score, PROMPT_VERSION, json.dumps(chunk_ids[:20])),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Sanity check endpoint
# ---------------------------------------------------------------------------

@app.get("/sanity")
def sanity_check():
    """Returns Ambedkar's predicted stance per axis. Expect all axes = 'anti'."""
    conn = get_conn()
    fig = conn.execute(
        "SELECT id FROM figures WHERE name LIKE '%Ambedkar%'"
    ).fetchone()
    if not fig:
        conn.close()
        return {"status": "no_data", "message": "Ambedkar not yet ingested"}

    # Pick the most recently computed verdict per axis (avoids stale multi-version duplicates)
    verdicts = conn.execute(
        """
        SELECT axis, stance, score FROM verdicts
        WHERE figure_id = ?
          AND (axis, computed_at) IN (
              SELECT axis, MAX(computed_at) FROM verdicts WHERE figure_id = ? GROUP BY axis
          )
        ORDER BY axis
        """,
        (fig["id"], fig["id"]),
    ).fetchall()
    conn.close()

    checks = [
        {**dict(v), "pass": v["stance"] == "anti"}
        for v in verdicts
    ]
    overall = all(c["pass"] for c in checks) if checks else False
    return {"figure": "Ambedkar", "overall_pass": overall, "axes": checks}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Ask endpoint — natural-language answer about a figure's caste stance
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434"

AXIS_LABELS = {
    "untouchability":   "untouchability (ritual impurity / social exclusion)",
    "varna_hierarchy":  "varna hierarchy (four-fold hereditary caste order)",
    "endogamy":         "endogamy (marrying within one's caste)",
    "temple_entry":     "temple entry (lower-caste access to Hindu temples)",
    "general_caste":    "the caste system overall",
    "communalism":      "communalism (anti-Muslim bias vs. Hindu-Muslim harmony)",
    "hindu_nationalism": "Hindu nationalism (promoting Hindu religious-political identity)",
}

STANCE_DESC = {
    "pro":  "supported / defended",
    "anti": "opposed / condemned",
    "mixed": "held a mixed or complex view on",
}

ASK_SYSTEM = """\
You are a concise expert on Indian history, the Hindu caste system, and social reform movements.
Answer the user's question about a historical figure based ONLY on the evidence provided.
Keep your answer to 3-5 sentences. Be specific: quote or paraphrase the source text where possible.
If the evidence is weak or missing for a given axis, say so honestly.
Do not invent facts not present in the evidence."""

ASK_PROMPT = """\
Figure: {name}

Computed stances (NLI model on their writings):
{verdict_block}

Representative excerpts from their writings (names masked as [PERSON]):
---
{chunks_block}
---

Question: {question}"""


def _verdict_block(verdicts: list) -> str:
    lines = []
    for v in verdicts:
        label = AXIS_LABELS.get(v["axis"], v["axis"])
        desc = STANCE_DESC.get(v["stance"], v["stance"])
        lines.append(f"- {label}: {desc} (score {v['score']:+.2f})")
    return "\n".join(lines) if lines else "(no scored verdicts yet)"


def _top_chunks(conn: sqlite3.Connection, figure_id: int, n: int = 6) -> list[str]:
    """Return up to n caste-relevant readable chunks, preferring those with keyword hits."""
    CASTE_KW = [
        "caste", "varna", "untouchab", "harijan", "dalit", "brahmin", "shudra",
        "scheduled caste", "four caste", "four varna", "chaturvarna",
    ]
    rows = conn.execute(
        """
        SELECT c.text_masked
        FROM chunks c JOIN works w ON w.id = c.work_id
        WHERE w.figure_id = ? AND c.readable = 1
        ORDER BY w.id, c.ord
        """,
        (figure_id,),
    ).fetchall()
    scored = []
    for r in rows:
        t = (r["text_masked"] or "").lower()
        hits = sum(1 for kw in CASTE_KW if kw in t)
        if hits > 0:
            scored.append((hits, r["text_masked"]))
    scored.sort(key=lambda x: -x[0])
    return [text[:600] for _, text in scored[:n]]


def _ollama_ask(prompt: str, system: str, model: str) -> str | None:
    try:
        import httpx
        r = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 400},
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception:
        return None


def _fallback_answer(name: str, verdicts: list, question: str) -> str:
    if not verdicts:
        return f"No scored verdicts found for {name}. Ingest their writings and run the scorer first."
    parts = []
    for v in verdicts:
        label = AXIS_LABELS.get(v["axis"], v["axis"])
        desc = STANCE_DESC.get(v["stance"], v["stance"])
        parts.append(f"{label} ({desc}, score {v['score']:+.2f})")
    stance_summary = "; ".join(parts)
    return (
        f"Based on NLI scoring of {name}'s writings: {stance_summary}. "
        f"Install Ollama and run `ollama pull llama3.2` for a richer natural-language answer."
    )


class AskRequest(BaseModel):
    figure: str
    question: str = "What was this person's stance on the caste system and untouchability?"
    model: str = "llama3.2"


@app.post("/ask")
def ask(req: AskRequest):
    conn = get_conn()

    fig = conn.execute(
        "SELECT id, name FROM figures WHERE name LIKE ?",
        (f"%{req.figure}%",),
    ).fetchone()
    if not fig:
        conn.close()
        raise HTTPException(404, f"No figure matching '{req.figure}'")

    verdicts = conn.execute(
        """
        SELECT axis, stance, score FROM verdicts
        WHERE figure_id = ?
          AND (axis, computed_at) IN (
              SELECT axis, MAX(computed_at) FROM verdicts WHERE figure_id = ? GROUP BY axis
          )
        ORDER BY axis
        """,
        (fig["id"], fig["id"]),
    ).fetchall()
    verdicts = [dict(v) for v in verdicts]

    chunks = _top_chunks(conn, fig["id"])
    conn.close()

    prompt = ASK_PROMPT.format(
        name=fig["name"],
        verdict_block=_verdict_block(verdicts),
        chunks_block="\n\n---\n\n".join(chunks) if chunks else "(no excerpts available)",
        question=req.question,
    )

    answer = _ollama_ask(prompt, ASK_SYSTEM, req.model)
    source = f"ollama:{req.model}" if answer else "fallback"
    if not answer:
        answer = _fallback_answer(fig["name"], verdicts, req.question)

    return {
        "figure": fig["name"],
        "question": req.question,
        "answer": answer,
        "source": source,
        "verdicts": verdicts,
        "num_evidence_chunks": len(chunks),
    }
