"""
LLM-based auto-labeler using a local Ollama model.

Sends each chunk to Ollama with a structured prompt that asks the model to
classify the author's stance on five caste-related axes. Writes results to
the annotations table as annotator='auto_llm:<model_name>'.

Usage:
    # Label all Ambedkar chunks with default model (llama3.2)
    python auto_label.py --figure "%Ambedkar%"

    # Use a different model, re-label already labeled chunks
    python auto_label.py --figure "%" --model mistral --force

    # Label only specific axes
    python auto_label.py --figure "%Gandhi%" --axes untouchability varna_hierarchy

Prerequisites:
    brew install ollama
    ollama serve           # in another terminal
    ollama pull llama3.2   # or mistral, llama3.1, phi3, etc.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

DB_PATH = Path(__file__).parent.parent / "db" / "whoismyside.db"

AXES = ["untouchability", "varna_hierarchy", "endogamy", "temple_entry", "general_caste",
        "communalism", "hindu_nationalism"]

OLLAMA_URL = "http://localhost:11434"

CLASSIFY_PROMPT = """\
You are an expert on Indian history and the Hindu caste system.
Read the following historical passage carefully and classify the AUTHOR'S OWN STANCE on each axis.

Important rules:
- If the author is QUOTING someone else's view, classify the quoted person's stance and set speaker_role to "quoted_other".
- If the author is DESCRIBING a historical practice without endorsing it, use "describing".
- Only use "author_asserted" when the author is clearly expressing their own position.
- Use "not_about_caste" when the passage has no meaningful content on that axis.
- Be strict: "pro" means the text SUPPORTS/DEFENDS the practice; "anti" means the text OPPOSES/CONDEMNS it.

Axes to classify:
- untouchability: treating certain communities as ritually impure / polluting
- varna_hierarchy: the four-fold hereditary varna system (Brahmin/Kshatriya/Vaishya/Shudra) as divinely ordained
- endogamy: the rule that Hindus must marry within their own caste
- temple_entry: exclusion of lower-caste people from Hindu temples
- general_caste: the caste system overall

Return ONLY valid JSON, no other text:
{{
  "speaker_role": "author_asserted" | "quoted_other" | "describing" | "ambiguous",
  "axes": {{
    "untouchability":  {{"stance": "pro"|"anti"|"mixed"|"not_about_caste", "confidence": 0.0-1.0, "reasoning": "<10 words>"}},
    "varna_hierarchy": {{"stance": "pro"|"anti"|"mixed"|"not_about_caste", "confidence": 0.0-1.0, "reasoning": "<10 words>"}},
    "endogamy":        {{"stance": "pro"|"anti"|"mixed"|"not_about_caste", "confidence": 0.0-1.0, "reasoning": "<10 words>"}},
    "temple_entry":    {{"stance": "pro"|"anti"|"mixed"|"not_about_caste", "confidence": 0.0-1.0, "reasoning": "<10 words>"}},
    "general_caste":   {{"stance": "pro"|"anti"|"mixed"|"not_about_caste", "confidence": 0.0-1.0, "reasoning": "<10 words>"}}
  }}
}}

Passage (author's name has been masked as [PERSON]):
\"\"\"
{text}
\"\"\"
"""

VALID_STANCES = {"pro", "anti", "mixed", "not_about_caste"}
VALID_ROLES = {"author_asserted", "quoted_other", "describing", "ambiguous"}


def check_ollama(model: str) -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code != 200:
            return False
        models = [m["name"].split(":")[0] for m in r.json().get("models", [])]
        if model not in models:
            print(f"Model '{model}' not found. Available: {models}")
            print(f"Run:  ollama pull {model}")
            return False
        return True
    except Exception:
        print(f"Ollama not reachable at {OLLAMA_URL}.")
        print("Start it with:  ollama serve")
        return False


def call_ollama(model: str, prompt: str, retries: int = 2) -> dict | None:
    for attempt in range(retries + 1):
        try:
            r = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.1, "num_predict": 512}},
                timeout=60,
            )
            r.raise_for_status()
            raw = r.json().get("response", "").strip()
            # Extract JSON even if the model wraps it in ```json ... ```
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                raise ValueError("No JSON object in response")
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == retries:
                print(f"  JSON parse failed after {retries+1} attempts: {e}")
                return None
            time.sleep(1)
        except Exception as e:
            if attempt == retries:
                print(f"  Ollama error: {e}")
                return None
            time.sleep(2)
    return None


def validate_response(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    role = data.get("speaker_role", "ambiguous")
    if role not in VALID_ROLES:
        role = "ambiguous"
    axes_out = {}
    for axis_data in data.get("axes", {}).items():
        axis, info = axis_data
        if axis not in AXES:
            continue
        stance = info.get("stance", "not_about_caste")
        if stance not in VALID_STANCES:
            stance = "not_about_caste"
        confidence = min(1.0, max(0.0, float(info.get("confidence", 0.5))))
        axes_out[axis] = {
            "stance": stance,
            "confidence": confidence,
            "reasoning": str(info.get("reasoning", ""))[:200],
        }
    if not axes_out:
        return None
    return {"speaker_role": role, "axes": axes_out}


def run(figure_like: str, model: str, axes: list, force: bool) -> None:
    if not check_ollama(model):
        sys.exit(1)

    annotator = f"auto_llm:{model}"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Fetch readable chunks for the figure
    chunks = conn.execute(
        """
        SELECT c.id, c.text_masked, c.text_raw, f.name AS figure_name
        FROM chunks c
        JOIN works w ON w.id = c.work_id
        JOIN figures f ON f.id = w.figure_id
        WHERE f.name LIKE ? AND c.readable = 1
        ORDER BY f.name, w.id, c.ord
        """,
        (figure_like,),
    ).fetchall()

    if not chunks:
        print("No readable chunks found for that figure filter.")
        return

    # If not force, skip chunks already fully annotated for all requested axes
    if not force:
        to_label = []
        for ch in chunks:
            existing = conn.execute(
                "SELECT axis FROM annotations WHERE chunk_id=? AND annotator=?",
                (ch["id"], annotator),
            ).fetchall()
            done_axes = {r["axis"] for r in existing}
            if not all(a in done_axes for a in axes):
                to_label.append(ch)
        chunks = to_label

    print(f"Labeling {len(chunks)} chunks with {model} across {axes} …")
    if not chunks:
        print("All chunks already labeled. Use --force to re-label.")
        return

    ok = skipped = errors = 0

    for i, ch in enumerate(chunks):
        text = (ch["text_masked"] or ch["text_raw"] or "").strip()
        if not text:
            skipped += 1
            continue

        prompt = CLASSIFY_PROMPT.format(text=text[:2000])
        raw = call_ollama(model, prompt)
        if raw is None:
            errors += 1
            continue

        validated = validate_response(raw)
        if validated is None:
            errors += 1
            continue

        role = validated["speaker_role"]
        for axis, info in validated["axes"].items():
            if axis not in axes:
                continue
            conn.execute(
                """
                INSERT INTO annotations
                    (chunk_id, annotator, speaker_role, axis, stance, confidence, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, annotator, axis) DO UPDATE SET
                    speaker_role = excluded.speaker_role,
                    stance       = excluded.stance,
                    confidence   = excluded.confidence,
                    notes        = excluded.notes,
                    created_at   = datetime('now')
                """,
                (
                    ch["id"], annotator, role, axis,
                    info["stance"], info["confidence"],
                    info["reasoning"],
                ),
            )
        ok += 1

        if (i + 1) % 10 == 0:
            conn.commit()
            pct = (i + 1) * 100 // len(chunks)
            print(f"  {i+1}/{len(chunks)} ({pct}%)  ok={ok} skip={skipped} err={errors}")

    conn.commit()
    print(f"\nDone. ok={ok} skipped={skipped} errors={errors}")

    # Show summary of what was written
    for fig_name in {ch["figure_name"] for ch in chunks}:
        fig_id = conn.execute(
            "SELECT id FROM figures WHERE name=?", (fig_name,)
        ).fetchone()["id"]
        print(f"\nAnnotation counts for {fig_name}:")
        for axis in axes:
            rows = conn.execute(
                """
                SELECT stance, COUNT(*) n FROM annotations
                WHERE chunk_id IN (
                    SELECT c.id FROM chunks c JOIN works w ON w.id=c.work_id WHERE w.figure_id=?
                ) AND annotator=? AND axis=?
                GROUP BY stance
                """,
                (fig_id, annotator, axis),
            ).fetchall()
            dist = {r["stance"]: r["n"] for r in rows}
            print(f"  {axis:22s}  {dist}")

    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="LLM auto-labeler via Ollama")
    p.add_argument("--figure", default="%", help="Figure name filter (SQL LIKE pattern)")
    p.add_argument("--model", default="llama3.2", help="Ollama model name")
    p.add_argument("--axes", nargs="+", default=AXES, choices=AXES)
    p.add_argument("--force", action="store_true", help="Re-label already labeled chunks")
    args = p.parse_args()
    run(args.figure, args.model, args.axes, args.force)
