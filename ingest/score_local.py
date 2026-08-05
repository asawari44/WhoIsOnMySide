"""
Local stance scorer — hybrid keyword + NLI cross-encoder.
No API key required. Uses cached cross-encoder/nli-MiniLM2-L6-H768.

Strategy per (chunk, axis):
  1. Compute keyword scores: count weighted anti/pro signal words.
  2. Run NLI entailment on a trimmed window of the chunk.
  3. Blend both signals; strong keyword match overrides weak NLI.
  4. Aggregate verdicts with author_asserted chunks weighted 2×.
"""

import json
import re
import sqlite3
from pathlib import Path

import torch
import torch.nn.functional as F
from sentence_transformers.cross_encoder import CrossEncoder

DB_PATH = Path(__file__).parent.parent / "db" / "whoismyside.db"
NLI_MODEL = "cross-encoder/nli-deberta-v3-large"
PROMPT_VERSION = "v10-deberta"

# ---------------------------------------------------------------------------
# Keyword lexicons — weighted by signal strength (2 = very strong)
# ---------------------------------------------------------------------------

KEYWORDS: dict[str, dict[str, list[tuple[str, float]]]] = {
    "general_caste": {
        "anti": [
            ("annihilation of caste", 2), ("destroy caste", 2), ("abolish caste", 2),
            ("caste must be", 2), ("caste is a curse", 2), ("caste is evil", 2),
            ("social equality", 1.5), ("caste prejudice", 1.5), ("caste discrimination", 1.5),
            ("eradicate caste", 2), ("caste is unjust", 2), ("caste oppression", 1.5),
            ("anti-caste", 2), ("caste system must", 1.5), ("end of caste", 1.5),
            ("untouchable", 1), ("outcaste", 1), ("depressed class", 1),
        ],
        "pro": [
            ("caste is divine", 2), ("caste is sacred", 2), ("divinely ordained", 2),
            ("varna dharma", 2), ("preserve caste", 2), ("caste purity", 2),
            ("caste system is beneficial", 2), ("hereditary occupation", 1),
        ],
    },
    "untouchability": {
        "anti": [
            ("untouchability must", 2), ("untouchability is wrong", 2),
            ("untouchability is a crime", 2), ("untouchability is evil", 2),
            ("uplift of untouchables", 2), ("rights of untouchables", 2),
            ("untouchable has a right", 2), ("abolish untouchability", 2),
            ("no untouchability", 2), ("untouchability cannot", 2),
            ("depressed classes", 1.5), ("social stigma", 1), ("pollution taboo", 1.5),
            ("treat them as human", 1.5), ("equal treatment", 1),
            # Ambedkar-specific vocabulary
            ("removal of untouchability", 2), ("removing untouchability", 2),
            ("abolition of caste and untouchability", 2),
            ("cause of the abolition", 1.5), ("sin of untouchability", 2),
            ("the untouchables", 1), ("alienate their orthodox", 1),
            ("self-respecting sect of untouchables", 2),
            # Savarkar's social-reform vocabulary
            ("remove untouchability", 2), ("untouchable brethren", 2),
            ("untouchable brothers", 2), ("suicidal social", 2),
            ("on the ground of untouchability", 2), ("based on birth alone", 2),
            ("touchable brothers", 1.5), ("shuddhi", 1),
            ("ban on shuddhi", 1.5),
            # Indira Gandhi's administrative/welfare vocabulary
            ("welfare of scheduled castes", 2), ("welfare of harijans", 2),
            ("protection of scheduled castes", 2), ("atrocities on harijans", 2),
            ("atrocities on adivasis", 1.5), ("harijans and adivasis", 1.5),
            ("stigma on society", 2), ("weaker sections of society", 1.5),
            ("rights of harijans", 2), ("uplift of harijans", 2),
            ("discrimination against harijans", 2),
            ("blot on the nation", 2), ("blot on our society", 2),
        ],
        "pro": [
            ("pollution by contact", 2), ("ritual impurity", 2),
            ("untouchables must not", 2), ("purity of caste", 2),
            ("contact is polluting", 2), ("necessary to keep separate", 2),
        ],
    },
    "varna_hierarchy": {
        "anti": [
            ("varna is man-made", 2), ("varna is not divine", 2),
            ("brahmin superiority is false", 2), ("no inherent superiority", 2),
            ("hereditary hierarchy", 1.5), ("birth should not determine", 2),
            ("equal dignity", 1.5), ("reject varna", 2), ("varna is unjust", 2),
            ("varna is a fiction", 2), ("destroy the varna", 2),
            # Ambedkar-specific anti-varna vocabulary
            ("priesthood must at least cease to be hereditary", 2),
            ("hereditary priesthood", 2), ("cease to be hereditary", 2),
            ("caste and varna", 1),  # Ambedkar uses this when criticising both
            ("not permit the hindu to use his reason", 2),
            ("shastras which teach", 1.5),
            ("complete annihilation", 2), ("annihilation of caste", 2),
        ],
        "pro": [
            ("god created four varnas", 2), ("brahmin is highest", 2),
            ("shudra must serve", 2), ("varna is divine", 2),
            ("sacred duty of varna", 2), ("divinely ordained varna", 2),
            # Gandhi-specific pro-varna language
            ("law of varna", 2), ("ancestral calling", 2),
            ("varna and ashrama", 2), ("varnashrama", 2),
            ("i believe in varna", 2), ("law of varnashrama", 2),
            ("follow the ancestral", 1.5), ("calling of his birth", 2),
            ("varna teaches", 2), ("varna has nothing to do with caste", 1.5),
            # Tilak-specific pro-varna language (Gita Rahasya)
            ("system of the four castes", 2), ("arrangement of the four castes", 2),
            ("inherent actions of ksatriyas", 2), ("ksatriyas, vaisyas, and sudras", 2),
            ("chatur varna", 2), ("four castes and other systems", 2),
            ("according to the arrangement of the four", 2),
            ("inherent actions of a brahmana", 2), ("inherent actions of a kshatriya", 2),
            ("inherently natural duty", 2), ("arrangement of the four classes", 2),
            ("inherently natural qualities", 2), ("natural duty of the sudra", 2),
            ("natural duty of the brahmin", 2), ("apply only to the arrangement of the four", 2),
        ],
    },
    "endogamy": {
        "anti": [
            ("inter-caste marriage", 2), ("inter caste marriage", 2),
            ("marry across caste", 2), ("marriage across castes", 2),
            ("freedom to marry", 1.5), ("endogamy is wrong", 2),
            ("caste endogamy must", 2), ("marriage barrier", 1.5),
        ],
        "pro": [
            ("marry within caste", 2), ("caste must be preserved through marriage", 2),
            ("inter-caste marriage is wrong", 2), ("purity of blood", 2),
            ("must not marry outside", 2),
        ],
    },
    "temple_entry": {
        "anti": [
            ("temple entry", 2), ("enter the temple", 1.5), ("right to enter temple", 2),
            ("denied temple", 2), ("temple access", 1.5), ("temple discrimination", 2),
            ("barred from temples", 2), ("temple worship is a right", 2),
            # Ambedkar-specific vocabulary
            ("excluded from the temples", 2), ("denied access to", 1.5),
            ("denied access to the interior of the hindu temples", 2),
            ("enter the sanctum", 2), ("enter the sanctorum", 2),
            ("mahad satyagraha", 2), ("kalaram temple", 2),
            ("temple for untouchables", 2), ("temple satyagraha", 2),
            ("access to temple", 1.5), ("right to worship", 1.5),
            ("no right to enter", 1.5), ("prevented from entering", 1.5),
            # Manu-quoting context — Ambedkar cites these as evidence of discrimination
            ("broken dish", 2), ("chandala", 2), ("chandal", 1.5),
            ("shall not walk about in", 2), ("at night they shall not", 2),
        ],
        "pro": [
            ("lower castes should not enter", 2), ("temple purity", 1.5),
            ("sacred spaces must be pure", 2), ("untouchables in temple would pollute", 2),
        ],
    },
    # communalism: "pro" = anti-Muslim/communalist bias in text,
    #              "anti" = secular / promotes Hindu-Muslim harmony
    "communalism": {
        "anti": [
            ("hindu-muslim unity", 2), ("hindu muslim unity", 2),
            ("communal harmony", 2), ("religious harmony", 2),
            ("oppose communalism", 2), ("communalism is wrong", 2),
            ("communal poison", 2), ("poison of communalism", 2),
            ("both hindus and muslims", 1.5), ("hindu muslim bhai bhai", 2),
            ("mohamedan brothers", 2), ("mussalman brethren", 2),
            ("muslims are our brothers", 2), ("unity of all religions", 1.5),
            ("equal rights to minorities", 2), ("protect minorities", 1.5),
            ("religious tolerance", 1.5), ("all religions are equal", 2),
        ],
        "pro": [
            # Only ultra-specific hostile Savarkar-ism phrases that can't appear in neutral texts
            ("their holyland is not india", 2), ("holy land is not india", 2),
            ("hindus and mussalmans can never unite", 2),
            ("hindus and muslims can never be one nation", 2),
            ("mussalman is an enemy", 2), ("muslim is a foreigner", 2),
            ("india is the land of hindus alone", 2),
            ("mohamedan domination over hindus", 2),
            ("forced to become mussalman by the sword", 2),
            ("recover those who were forcibly converted to islam", 2),
        ],
    },
    # hindu_nationalism: "pro" = promotes Hindu religious/cultural nationalism,
    #                    "anti" = secular / rationalist / anti-nationalist
    "hindu_nationalism": {
        "anti": [
            ("separation of religion from politics", 2), ("religion is personal", 1.5),
            ("secular state", 2), ("india is secular", 2),
            ("reject religion", 1.5), ("superstition", 1.5), ("irrationalism", 1.5),
            ("hinduism is irrational", 2), ("religion as opium", 1.5),
            ("free from religion", 1.5), ("religion has ruined", 1.5),
            # Ambedkar's vocabulary
            ("annihilate the caste and religion", 2), ("religion is the enemy", 1.5),
            ("vedas are not infallible", 2), ("reject the vedas", 2),
            ("brahminism must go", 2), ("shastras are wrong", 1.5),
            ("burn the manusmriti", 2),
        ],
        "pro": [
            # Savarkar's Hindu nationalism vocabulary
            ("hindu rashtra", 2), ("hindu nation", 2), ("hindutva", 2),
            ("hindustan belongs to hindus", 2), ("hindu is the master of india", 2),
            ("akhand hindustan", 2), ("akhand bharat", 1.5),
            # Tilak's vocabulary
            ("ganapati festival", 1.5), ("shivaji festival", 1.5),
            ("swaraj is my birthright", 1.5), ("hinduism is the basis", 2),
            # Gandhi's vocabulary
            ("ram rajya", 2), ("ramarajya", 2), ("god is truth", 1),
            ("hinduism is the noblest", 2), ("vedic religion", 1.5),
            ("sanatana dharma", 1.5), ("cow is our mother", 1.5), ("gau mata", 2),
            # General Hindu nationalism
            ("india is a hindu land", 2), ("protecting hinduism", 1.5),
            ("defend hinduism", 1.5), ("glory of hinduism", 1.5),
        ],
    },
}

AXIS_NLI_HYPOTHESES = {
    "general_caste": (
        "This passage argues against the caste system.",
        "This passage argues in favour of the caste system.",
    ),
    "untouchability": (
        "This passage argues that untouchability is wrong.",
        "This passage argues that untouchability is acceptable.",
    ),
    "varna_hierarchy": (
        "This passage argues that hereditary varna ranking is wrong.",
        "This passage argues that the four-varna hierarchy is correct.",
    ),
    "endogamy": (
        "This passage argues that inter-caste marriage should be allowed.",
        "This passage argues that caste endogamy must be enforced.",
    ),
    "temple_entry": (
        "This passage argues that lower-caste people should be allowed into temples.",
        "This passage argues that lower-caste people should be excluded from temples.",
    ),
    "communalism": (
        "This passage promotes Hindu-Muslim unity or argues against communal discrimination.",
        "This passage expresses hostility toward Muslims or promotes Hindu communal supremacy.",
    ),
    "hindu_nationalism": (
        "This passage argues for secularism or against Hindu religious nationalism.",
        "This passage promotes Hindu religious nationalism or defines India as a Hindu nation.",
    ),
}

QUOTE_RE = re.compile(r'[""\'"].{10,200}[""\'"]')
ROLE_WEIGHT = {"author_asserted": 2.0, "quoted_other": 1.0, "describing": 0.5, "ambiguous": 1.0}
STANCE_VALUES = {"pro": 1.0, "anti": -1.0, "mixed": 0.0}

# Topic-relevance gate: a chunk must mention at least one of these tokens
# to be scored at all. Covers caste, communalism, and religious-nationalism axes.
CASTE_TOPIC_TOKENS = {
    # Caste / untouchability
    "caste", "varna", "brahmin", "kshatriya", "vaishya", "shudra",
    "untouchab", "harijan", "dalit",
    "scheduled caste", "scheduled tribe", "depressed class",
    "backward caste", "backward class",
    "atrocities on", "temple entry", "temple-entry",
    "endogam", "jati", "weaker section",
    # Communalism / Muslim relations
    "muslim", "mohamedan", "mussalman", "islam", "communal",
    "hindu-muslim", "hindu muslim", "minority", "mosque",
    # Hindu nationalism
    "hindutva", "hindu rashtra", "hindu nation", "sanatana", "sanatan",
    "ram rajya", "ramarajya", "gau mata",
}

# Per-axis topic gates — a chunk is only NLI-scored on an axis if it mentions
# at least one of these tokens OR has a keyword hit (kw_total > 0) for that axis.
# Prevents Tilak's varna-dharma text from scoring on 'untouchability', etc.
AXIS_TOPIC_TOKENS: dict[str, set[str]] = {
    "untouchability": {
        "untouchab", "harijan", "dalit", "panchama", "chandala", "chandal",
        "depressed class", "broken dish", "suicidal social",
        "touchable", "outcast", "outcaste",
    },
    "varna_hierarchy": {
        "varna", "brahmin", "brahmana", "kshatriya", "vaishya", "shudra", "sudra",
        "four caste", "four varna", "chaturvarna", "chatur varna",
        "caste", "jati", "inherent action", "svadharma", "swadharma",
        "varna-dharma", "varna dharma",
    },
    "endogamy": {
        "marriage", "marry", "marrying", "married", "endogam",
        "inter-caste", "inter caste", "matrimon", "widow",
    },
    "temple_entry": {
        "temple", "shrine", "worship", "sanctum", "chandala", "broken dish",
        "mahad", "kalaram", "sacred place", "place of worship",
    },
    "general_caste": {
        "caste", "varna", "harijan", "dalit", "untouchab", "jati",
        "brahmin", "shudra", "sudra", "brahmana", "scheduled caste",
        "depressed class", "backward caste",
    },
    "communalism": {
        "muslim", "mohamedan", "mussalman", "islam", "communal",
        "hindu-muslim", "hindu muslim", "minority", "mosque",
        "pakistan", "partition", "cow slaughter", "cow protection",
        "conversion", "forcible conversion",
    },
    "hindu_nationalism": {
        "hindutva", "hindu rashtra", "hindu nation", "sanatana", "sanatan dharma",
        "ram rajya", "ramarajya", "gau mata",
        "vedic", "vedas", "shastras", "manusmriti", "religion", "dharma",
        "ganapati", "shivaji", "swaraj",
    },
}


def infer_speaker_role(text: str) -> str:
    return "quoted_other" if QUOTE_RE.search(text) else "author_asserted"


def keyword_score(text: str, axis: str) -> tuple[float, float]:
    """Returns (anti_score, pro_score) from keyword matches."""
    text_lower = text.lower()
    lexicon = KEYWORDS.get(axis, {"anti": [], "pro": []})
    anti = sum(w for kw, w in lexicon["anti"] if kw in text_lower)
    pro = sum(w for kw, w in lexicon["pro"] if kw in text_lower)
    return anti, pro


def entailment_scores(model: CrossEncoder, text: str, h_anti: str, h_pro: str) -> tuple[float, float]:
    raw = model.predict([(text, h_anti), (text, h_pro)])
    probs = [float(F.softmax(torch.tensor(s), dim=0)[1]) for s in raw]
    return probs[0], probs[1]


def clean_ocr(text: str) -> str:
    text = re.sub(r'(?<=[a-z])- (?=[a-z])', '', text)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def is_caste_relevant(text: str) -> bool:
    """Return True if the chunk mentions any caste-related vocabulary."""
    t = text.lower()
    return any(tok in t for tok in CASTE_TOPIC_TOKENS)


def is_axis_relevant(text: str, axis: str, kw_anti: float, kw_pro: float) -> bool:
    """Return True if the chunk is relevant to this specific axis.
    A chunk with keyword hits (kw_total > 0) is always considered relevant.
    Otherwise fall back to the axis-specific topic token set."""
    if kw_anti + kw_pro > 0:
        return True
    t = text.lower()
    return any(tok in t for tok in AXIS_TOPIC_TOKENS.get(axis, set()))


def is_readable(text: str, min_word_ratio: float = 0.45) -> bool:
    """
    Return False if the chunk is mostly OCR garbage (inverted text, mirrored, etc.).
    Heuristic: count tokens that look like English words (3+ alpha chars) vs total tokens.
    """
    tokens = text.split()
    if len(tokens) < 10:
        return False
    alpha_words = sum(1 for t in tokens if sum(c.isalpha() for c in t) >= 3)
    return (alpha_words / len(tokens)) >= min_word_ratio


def classify(kw_anti: float, kw_pro: float, nli_anti: float, nli_pro: float) -> tuple[str, float]:
    """
    Blend keyword and NLI signals.
    Strong keyword matches (sum > 3) override NLI entirely.
    """
    kw_total = kw_anti + kw_pro
    kw_delta = kw_anti - kw_pro

    nli_delta = nli_anti - nli_pro
    nli_max = max(nli_anti, nli_pro)

    if kw_total >= 3:
        # Strong keyword signal — trust it
        delta = kw_delta
        confidence = min(1.0, kw_total / 10)
    elif kw_total > 0:
        # Weak keyword + NLI blend
        delta = 0.6 * kw_delta + 0.4 * nli_delta
        confidence = min(1.0, kw_total / 5 + nli_max * 0.3)
    else:
        # Keyword silent — rely on NLI alone
        delta = nli_delta
        confidence = nli_max

    if confidence < 0.15:
        return "not_about_caste", round(confidence, 4)
    if delta > 0.05:
        return "anti", round(confidence, 4)
    if delta < -0.05:
        return "pro", round(confidence, 4)
    return "mixed", round(confidence, 4)


def run(figure_name_like: str = "%", axes: list | None = None) -> None:
    axes = axes or list(KEYWORDS.keys())

    print(f"Loading {NLI_MODEL} …")
    model = CrossEncoder(NLI_MODEL)
    print("Model ready.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("DELETE FROM predictions WHERE model_name = ?", (NLI_MODEL,))
    conn.commit()

    rows = conn.execute(
        """
        SELECT c.id, c.text_masked, c.text_raw, w.figure_id
        FROM chunks c
        JOIN works w ON w.id = c.work_id
        JOIN figures f ON f.id = w.figure_id
        WHERE f.name LIKE ? AND c.readable = 1
        """,
        (figure_name_like,),
    ).fetchall()

    print(f"Scoring {len(rows)} chunks × {len(axes)} axes …")

    for i, ch in enumerate(rows):
        raw_text = (ch["text_raw"] or "").strip()
        masked = (ch["text_masked"] or raw_text).strip()
        clean = clean_ocr(masked)[:1200]
        if not clean or not is_readable(clean):
            continue
        if not is_caste_relevant(raw_text):
            continue
        role = infer_speaker_role(raw_text)

        h_pairs = [(clean, AXIS_NLI_HYPOTHESES[a][0], AXIS_NLI_HYPOTHESES[a][1]) for a in axes]
        nli_results = model.predict(
            [(text, hyp) for text, h_anti, h_pro in h_pairs for hyp in (h_anti, h_pro)]
        )
        nli_probs = [float(F.softmax(torch.tensor(s), dim=0)[1]) for s in nli_results]

        for j, axis in enumerate(axes):
            kw_anti, kw_pro = keyword_score(raw_text, axis)
            if not is_axis_relevant(raw_text, axis, kw_anti, kw_pro):
                continue
            nli_anti = nli_probs[j * 2]
            nli_pro = nli_probs[j * 2 + 1]
            stance, confidence = classify(kw_anti, kw_pro, nli_anti, nli_pro)

            conn.execute(
                """
                INSERT INTO predictions
                    (chunk_id, model_name, prompt_version, speaker_role, axis, stance, score, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ch["id"], NLI_MODEL, PROMPT_VERSION, role,
                    axis, stance, confidence,
                    json.dumps({"kw_anti": kw_anti, "kw_pro": kw_pro,
                                "nli_anti": round(nli_anti, 4), "nli_pro": round(nli_pro, 4)}),
                ),
            )

        if (i + 1) % 10 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(rows)}")

    conn.commit()

    figures = conn.execute(
        "SELECT DISTINCT f.id, f.name FROM figures f JOIN works w ON w.figure_id = f.id "
        "JOIN chunks c ON c.work_id = w.id WHERE f.name LIKE ?",
        (figure_name_like,),
    ).fetchall()

    for fig in figures:
        _recompute_verdicts(conn, fig["id"], axes)
        print(f"\nVerdicts for {fig['name']}:")
        for v in conn.execute(
            "SELECT axis, stance, score FROM verdicts WHERE figure_id = ? AND method_version = ? ORDER BY axis",
            (fig["id"], PROMPT_VERSION),
        ).fetchall():
            mark = "PASS ✓" if v["stance"] == "anti" else "FAIL ✗" if v["stance"] == "pro" else "~   "
            print(f"  {mark}  {v['axis']:22s}  {v['stance']:18s}  score={v['score']:.4f}")

    conn.close()


def _recompute_verdicts(conn: sqlite3.Connection, figure_id: int, axes: list) -> None:
    for axis in axes:
        rows = conn.execute(
            """
            SELECT p.stance, p.speaker_role, p.score, p.chunk_id
            FROM predictions p
            JOIN chunks c ON c.id = p.chunk_id
            JOIN works w ON w.id = c.work_id
            WHERE w.figure_id = ? AND p.axis = ? AND p.model_name = ? AND p.prompt_version = ?
            """,
            (figure_id, axis, NLI_MODEL, PROMPT_VERSION),
        ).fetchall()

        scored = [r for r in rows if r["stance"] in STANCE_VALUES]
        if not scored:
            # No predictions for this axis — clear any stale verdict
            conn.execute(
                "DELETE FROM verdicts WHERE figure_id=? AND axis=? AND method_version=?",
                (figure_id, axis, PROMPT_VERSION),
            )
            continue

        total_weight = weighted_sum = 0.0
        chunk_ids = []
        for r in scored:
            w = ROLE_WEIGHT.get(r["speaker_role"], 1.0)
            weighted_sum += STANCE_VALUES[r["stance"]] * w * (r["score"] or 1.0)
            total_weight += w
            chunk_ids.append(r["chunk_id"])

        score = weighted_sum / total_weight if total_weight else 0.0
        stance = "anti" if score < -0.05 else "pro" if score > 0.05 else "mixed"

        conn.execute(
            """
            INSERT INTO verdicts(figure_id, axis, stance, score, method_version, evidence_chunk_ids)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(figure_id, axis, method_version) DO UPDATE SET
                stance = excluded.stance, score = excluded.score,
                evidence_chunk_ids = excluded.evidence_chunk_ids,
                computed_at = datetime('now')
            """,
            (figure_id, axis, stance, score, PROMPT_VERSION, json.dumps(chunk_ids[:20])),
        )
    conn.commit()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--figure", default="%")
    p.add_argument("--axes", nargs="+", default=list(KEYWORDS.keys()))
    args = p.parse_args()
    run(args.figure, args.axes)
