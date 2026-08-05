PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS figures (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    birth_year  INTEGER,
    death_year  INTEGER,
    bio_summary TEXT
);

CREATE TABLE IF NOT EXISTS works (
    id          INTEGER PRIMARY KEY,
    figure_id   INTEGER NOT NULL REFERENCES figures(id),
    title       TEXT NOT NULL,
    year_written INTEGER,
    language    TEXT DEFAULT 'en',
    source_url  TEXT,
    ingested_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    work_id     INTEGER NOT NULL REFERENCES works(id),
    ord         INTEGER NOT NULL,    -- ordering within the work
    text_raw    TEXT NOT NULL,
    text_masked TEXT,               -- names + giveaway phrases stripped
    readable    INTEGER NOT NULL DEFAULT 1,  -- 0 = OCR garbage, excluded from UI + scoring
    embedding   BLOB                -- stored as float32 bytes if precomputed
);

-- Human labels. One row per (chunk, annotator, axis).
CREATE TABLE IF NOT EXISTS annotations (
    id           INTEGER PRIMARY KEY,
    chunk_id     INTEGER NOT NULL REFERENCES chunks(id),
    annotator    TEXT NOT NULL DEFAULT 'human',
    speaker_role TEXT NOT NULL CHECK(speaker_role IN (
                     'author_asserted', 'quoted_other',
                     'describing', 'ambiguous')),
    axis         TEXT NOT NULL CHECK(axis IN (
                     'untouchability', 'varna_hierarchy',
                     'endogamy', 'temple_entry', 'general_caste',
                     'communalism', 'hindu_nationalism')),
    stance       TEXT NOT NULL CHECK(stance IN (
                     'pro', 'anti', 'mixed', 'not_about_caste')),
    confidence   REAL CHECK(confidence BETWEEN 0 AND 1),
    notes        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(chunk_id, annotator, axis)
);

-- Model predictions — separate from human labels so we can compare.
CREATE TABLE IF NOT EXISTS predictions (
    id             INTEGER PRIMARY KEY,
    chunk_id       INTEGER NOT NULL REFERENCES chunks(id),
    model_name     TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    speaker_role   TEXT NOT NULL CHECK(speaker_role IN (
                       'author_asserted', 'quoted_other',
                       'describing', 'ambiguous')),
    axis           TEXT NOT NULL CHECK(axis IN (
                       'untouchability', 'varna_hierarchy',
                       'endogamy', 'temple_entry', 'general_caste')),
    stance         TEXT NOT NULL CHECK(stance IN (
                       'pro', 'anti', 'mixed', 'not_about_caste')),
    score          REAL,            -- confidence or similarity score
    raw_response   TEXT,            -- full LLM output for debugging
    created_at     TEXT DEFAULT (datetime('now'))
);

-- Aggregated verdict per (figure, axis) — recomputed from predictions+annotations.
-- author_asserted chunks are weighted 2× quoted_other.
CREATE TABLE IF NOT EXISTS verdicts (
    id                 INTEGER PRIMARY KEY,
    figure_id          INTEGER NOT NULL REFERENCES figures(id),
    axis               TEXT NOT NULL CHECK(axis IN (
                           'untouchability', 'varna_hierarchy',
                           'endogamy', 'temple_entry', 'general_caste')),
    stance             TEXT NOT NULL CHECK(stance IN (
                           'pro', 'anti', 'mixed', 'not_about_caste', 'unknown')),
    score              REAL,
    method_version     TEXT NOT NULL,
    evidence_chunk_ids TEXT,        -- JSON array of chunk ids
    computed_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(figure_id, axis, method_version)
);

CREATE INDEX IF NOT EXISTS idx_chunks_work    ON chunks(work_id);
CREATE INDEX IF NOT EXISTS idx_annotations_chunk ON annotations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_predictions_chunk ON predictions(chunk_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_figure   ON verdicts(figure_id);
