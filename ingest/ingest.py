"""
Ingest public-domain texts for a figure from Wikipedia + Wikisource.
Usage:
    python ingest.py --name "B.R. Ambedkar" --work "Annihilation of Caste" \
                     --url "https://en.wikisource.org/wiki/Annihilation_of_Caste"
"""

import argparse
import re
import sqlite3
import textwrap
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

DB_PATH = Path(__file__).parent.parent / "db" / "whoismyside.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"
CHUNK_SIZE = 400  # words per chunk (approx 2-3 paragraphs)

# Phrases whose presence in a chunk strongly signals the author — strip before scoring.
GIVEAWAY_PHRASES = [
    r"\bAmbedkar\b",
    r"\bBhimrao\b",
    r"\bGandhi\b",
    r"\bMahatma\b",
    r"\bIndira\b",
    r"\bTilak\b",
    r"\bNehru\b",
    r"\bManu(?:smriti)?\b",
    r"\bSavarkar\b",
    r"\bTagore\b",
    r"\bPhule\b",
    r"\bPeriyar\b",
    r"\bNarendra\b",
    r"\bModi\b",
]
_GIVEAWAY_RE = re.compile("|".join(GIVEAWAY_PHRASES), re.IGNORECASE)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def get_or_create_figure(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM figures WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO figures(name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def get_or_create_work(
    conn: sqlite3.Connection,
    figure_id: int,
    title: str,
    source_url: str | None,
) -> int:
    row = conn.execute(
        "SELECT id FROM works WHERE figure_id = ? AND title = ?",
        (figure_id, title),
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO works(figure_id, title, source_url) VALUES (?, ?, ?)",
        (figure_id, title, source_url),
    )
    conn.commit()
    return cur.lastrowid


def fetch_text_from_wikisource(url: str) -> str:
    """Download a Wikisource page and extract the main body text."""
    headers = {"User-Agent": "WhoIsOnMySide/0.1 (historical-text-research; https://github.com/local/whoismyside)"}
    resp = httpx.get(url, follow_redirects=True, timeout=30, headers=headers)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Wikisource wraps content in <div class="mw-parser-output">
    content = soup.find("div", class_="mw-parser-output")
    if not content:
        raise ValueError(f"Could not find mw-parser-output on {url}")

    paragraphs = []
    for tag in content.find_all(["p", "h2", "h3", "blockquote"]):
        text = tag.get_text(" ", strip=True)
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


def clean_ocr(text: str) -> str:
    """
    Normalise common DjVu OCR artefacts before chunking.
    Applied to the full document text, not per-chunk.
    """
    # Fix soft-hyphen line breaks: "some-\nwhere" → "somewhere"
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
    # Collapse mid-word spaces inserted by OCR: "s o c i e t y" → "society"
    # (only when every token is a single letter in a run of 4+)
    text = re.sub(r'\b([a-zA-Z] ){3,}[a-zA-Z]\b', lambda m: m.group().replace(' ', ''), text)
    # Strip non-ASCII (mirrored/inverted OCR pages produce Hebrew/Arabic code points)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    # Remove isolated single characters that aren't meaningful (page number noise)
    text = re.sub(r'(?<!\w)[^a-zA-Z0-9\s]{2,}(?!\w)', ' ', text)
    # Normalise whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_readable(chunk: str, min_words: int = 30, min_alpha_ratio: float = 0.45) -> bool:
    """
    Return False for chunks that are mostly OCR garbage.

    Two checks:
    1. Too few words — likely a title page, header, or mostly blank.
    2. Too few recognisable words (≥3 alpha chars) — likely inverted/mirrored scan.
    """
    tokens = chunk.split()
    if len(tokens) < min_words:
        return False
    alpha_words = sum(1 for t in tokens if sum(c.isalpha() for c in t) >= 3)
    return (alpha_words / len(tokens)) >= min_alpha_ratio


def chunk_text(text: str) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), CHUNK_SIZE):
        chunk = " ".join(words[i : i + CHUNK_SIZE])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def mask_text(text: str) -> str:
    return _GIVEAWAY_RE.sub("[PERSON]", text)


def ingest_work(
    conn: sqlite3.Connection,
    figure_name: str,
    work_title: str,
    url: str,
) -> int:
    print(f"Fetching {work_title!r} from {url}")
    raw_text = fetch_text_from_wikisource(url)

    figure_id = get_or_create_figure(conn, figure_name)
    work_id = get_or_create_work(conn, figure_id, work_title, url)

    existing = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE work_id = ?", (work_id,)
    ).fetchone()[0]
    if existing:
        print(f"  Already have {existing} chunks for this work — skipping re-ingest.")
        return existing

    cleaned = clean_ocr(raw_text)
    raw_chunks = chunk_text(cleaned)
    readable = [c for c in raw_chunks if is_readable(c)]
    dropped = len(raw_chunks) - len(readable)
    if dropped:
        print(f"  Dropped {dropped} garbage chunks ({dropped*100//len(raw_chunks)}%).")

    rows = [
        (work_id, ord_, chunk, mask_text(chunk), 1)
        for ord_, chunk in enumerate(readable)
    ]
    conn.executemany(
        "INSERT INTO chunks(work_id, ord, text_raw, text_masked, readable) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"  Stored {len(rows)} chunks.")
    return len(rows)


def ingest_from_plaintext(
    conn: sqlite3.Connection,
    figure_name: str,
    work_title: str,
    filepath: str,
) -> int:
    raw_text = Path(filepath).read_text(encoding="utf-8")
    figure_id = get_or_create_figure(conn, figure_name)
    work_id = get_or_create_work(conn, figure_id, work_title, None)

    cleaned = clean_ocr(raw_text)
    raw_chunks = chunk_text(cleaned)
    readable = [c for c in raw_chunks if is_readable(c)]
    dropped = len(raw_chunks) - len(readable)
    if dropped:
        print(f"  Dropped {dropped} garbage chunks ({dropped*100//max(len(raw_chunks),1)}%).")

    rows = [
        (work_id, ord_, chunk, mask_text(chunk), 1)
        for ord_, chunk in enumerate(readable)
    ]
    conn.executemany(
        "INSERT INTO chunks(work_id, ord, text_raw, text_masked, readable) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"Stored {len(rows)} chunks from {filepath}.")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a work into WhoIsOnMySide DB")
    parser.add_argument("--name", required=True, help="Historical figure name")
    parser.add_argument("--work", required=True, help="Work title")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Wikisource URL to fetch from")
    group.add_argument("--file", help="Path to local plain-text file")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.url:
        ingest_work(conn, args.name, args.work, args.url)
    else:
        ingest_from_plaintext(conn, args.name, args.work, args.file)

    conn.close()


if __name__ == "__main__":
    main()
