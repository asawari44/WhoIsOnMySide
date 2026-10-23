# WhoIsOnMySide

Stance classifier for historical Indian political figures. Given their published writings and speeches, the system scores each figure on a set of social and political axes using a hybrid keyword + NLI (Natural Language Inference) model — no API key required, runs fully offline.

---

## What It Does

You can ask questions like:
- "Was Tilak actually progressive on caste?"
- "Did Savarkar oppose untouchability in practice?"
- "Where did Gandhi and Ambedkar actually agree?"

The answer is grounded in each figure's own words, not Wikipedia summaries or political reputation.

---

## Current State

### Figures Ingested

| Figure | Source texts | Chunks |
|---|---|---|
| B.R. Ambedkar | Annihilation of Caste, The Untouchables | 191 |
| Mahatma Gandhi | Caste Must Go, Hinduism and Untouchability, Vindication of Caste | 78 |
| Indira Gandhi | Parliament speeches 1966–1977 (Lok Sabha) | 1,252 |
| Bal Gangadhar Tilak | Gita Rahasya, Home Rule speeches | 672 |
| V.D. Savarkar | Hindutva, Hindu Rashtra Darshan | 334 |
| Narendra Modi | Curated speech excerpts on caste/social equality | 3 |

### Scored Axes (7 total)

| Axis | What "pro" means | What "anti" means |
|---|---|---|
| `untouchability` | supports ritual exclusion of communities | opposes untouchability |
| `varna_hierarchy` | defends hereditary four-varna order | rejects birth-based hierarchy |
| `endogamy` | enforces caste-based marriage | supports inter-caste marriage |
| `temple_entry` | excludes lower-caste people from temples | supports equal temple access |
| `general_caste` | defends the caste system overall | opposes the caste system |
| `communalism` | shows anti-Muslim bias / Hindu supremacism | secular / pro Hindu-Muslim harmony |
| `hindu_nationalism` | promotes Hindu religious-political identity | secular / rationalist |

### Current Verdicts (latest scoring run)

| Figure | Untouchability | Varna | Communalism | Hindu Nationalism |
|---|---|---|---|---|
| Ambedkar | **anti** | **anti** | pro* | **anti** |
| Mahatma Gandhi | **anti** | pro | **anti** | pro |
| Indira Gandhi | **anti** | **anti** | mixed | mixed |
| Tilak | — | pro | pro | pro |
| Savarkar | **anti** | **anti** | pro | pro |
| Modi | **anti** (strong) | **anti** | — | — |

*Ambedkar's `communalism=pro` is a known false positive — his academic texts discuss Muslim communities historically without anti-Muslim intent. See Known Issues.

---

## Architecture

```
ingest/
  ingest.py          — download from Wikisource or load local .txt → DB chunks
  score_local.py     — NLI scorer: DeBERTa-large cross-encoder + keyword lexicon
  auto_label.py      — Ollama LLM auto-labeler (optional, improves labels)
  *.txt              — source text files for each figure

backend/
  main.py            — FastAPI: /figures, /chunks, /label, /predict, /ask

frontend/src/
  pages/
    FigureBrowser.tsx  — per-figure verdict chips + chunk browser
    LabelingUI.tsx     — manual chunk labeling interface
    SanityDashboard.tsx — score distribution / sanity checks
    AskPage.tsx        — natural language Q&A grounded in verdicts + chunks

db/
  schema.sql         — SQLite schema (figures, works, chunks, annotations, predictions, verdicts)
  whoismyside.db     — the database
```

### Scoring Pipeline

```
text file → ingest.py → chunks (400 words each, names masked)
                          ↓
                    score_local.py
                      1. Global topic gate (CASTE_TOPIC_TOKENS) — skip off-topic chunks
                      2. Per-axis topic gate (AXIS_TOPIC_TOKENS) — skip axis-irrelevant chunks
                      3. Keyword scoring — strong keyword hits override NLI
                      4. NLI: cross-encoder/nli-deberta-v3-large (~400MB)
                      5. Blend: keyword × 0.6 + NLI × 0.4 (when keyword weak)
                      6. Weighted verdict: author_asserted=2×, quoted_other=1×
                          ↓
                    verdicts table → API → frontend
```

### NLI Model

`cross-encoder/nli-deberta-v3-large` — downloaded on first run (~400 MB), cached in `~/.cache/huggingface/`.

---

## Running It

### Prerequisites

```bash
# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r ingest/requirements.txt
pip install -r backend/requirements.txt

# Frontend
cd frontend && npm install
```

### Start

```bash
./start.sh
# OR manually:
.venv/bin/uvicorn backend.main:app --port 8000 &
cd frontend && npm run dev
```

Open `http://localhost:5173`.

### Add a New Figure

```bash
# From a Wikisource URL
python ingest/ingest.py --name "Figure Name" \
  --work "Work Title" \
  --url "https://en.wikisource.org/wiki/..."

# From a local text file
python ingest/ingest.py --name "Figure Name" \
  --work "Work Title" \
  --file ingest/figure_text.txt

# Re-score (all figures, all axes)
python ingest/score_local.py

# Score a single figure
python ingest/score_local.py --figure "Figure Name"
```

### Optional: Ollama LLM Labels

Richer auto-labels using a local LLM (improves precision vs. pure NLI):

```bash
brew install ollama
ollama serve        # in a separate terminal
ollama pull llama3.2

python ingest/auto_label.py --figure "%Ambedkar%"
```

### Optional: Ask Mode

With Ollama running, the `/ask` endpoint generates a grounded natural-language answer:

```bash
# From the Ask tab in the UI, or:
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"figure": "Ambedkar", "question": "What was his stance on inter-caste marriage?"}'
```

Falls back to a structured verdict summary if Ollama is not running.

---

## Known Issues

| Issue | Status |
|---|---|
| **Ambedkar `communalism=pro`** | False positive — Ambedkar uses "Mussalman"/"Mohamedan" in neutral academic analysis of how Muslim society treats Dalits. The NLI reads this as communalist. Needs better topic-gate phrases or a context-aware rewrite. |
| **Modi corpus is tiny (3 chunks)** | Only public speech excerpts accessible; narendramodi.in and pib.gov.in block automated fetching. No verdicts for `communalism` or `hindu_nationalism`. |
| **Savarkar `communalism` score low (0.11)** | Hindutva's anti-Muslim framing is structural/philosophical rather than explicit-slur-based, so keyword hits are sparse and NLI alone gives a weaker signal than expected. |
| **Tilak `untouchability` — no verdict** | Gita Rahasya is purely philosophical; it never discusses untouchability directly, so the per-axis topic gate correctly suppresses it. Historically accurate but might look like a gap. |
| **Gandhi `varna_hierarchy=pro`** | Historically accurate — Gandhi explicitly defended the varna system while opposing untouchability. The score (0.13) is weak but correct directionally. |

---

## What's Left / Future Work

### Short-term (pipeline fixes)
- [ ] Fix Ambedkar communalism false positive — add context-aware gate that ignores academic discussion of Muslim communities
- [ ] Re-score after fix and verify all verdicts are stable
- [ ] Add `--axes` flag to `score_local.py --figure` so partial re-scores don't wipe unrelated predictions

### More Figures
- [ ] **Jawaharlal Nehru** — Parliament speeches available on eparlib.nic.in; strong secular / anti-caste signals expected
- [ ] **Periyar (E.V. Ramasamy)** — Wikisource has Tamil texts; strongest anti-caste signal in the corpus
- [ ] **Jyotiba Phule** — Wikisource; earlier anti-caste reformer
- [ ] **Subhas Chandra Bose** — INA speeches; interesting communalism / nationalism contrast
- [ ] **Vallabhbhai Patel** — Parliament records
- [ ] **Narendra Modi** — Needs accessible full speech texts; government websites currently block fetching

### Scoring Improvements
- [ ] **Confidence intervals** — With small corpora (Modi: 3 chunks), show uncertainty rather than a point estimate
- [ ] **Cross-validation** — For figures with many chunks, hold out 20% and check verdict stability
- [ ] **Source attribution** — Show which specific speech / book each verdict chunk came from
- [ ] **LLM labels at scale** — Use auto_label.py on all figures; integrate LLM labels into verdict aggregation (currently NLI-only)
- [ ] **Embed + cluster** — Add embeddings to chunks for semantic search ("find all chunks about varna")

### Axes to Add
- [ ] **Feminism / women's rights** — Most figures have clear stances; text signals are strong
- [ ] **Economic left/right** — Socialism vs. capitalism; distinguishes Nehru/Ambedkar from Savarkar/Modi
- [ ] **Anti-colonialism intensity** — Distinguishes moderates (Gokhale) from radicals (Bose, Savarkar early)

### UI / Product
- [ ] **Side-by-side comparison** — Select two figures and see their verdicts compared axis by axis
- [ ] **Evidence drill-down** — Click a verdict chip to see the 5 strongest supporting chunks
- [ ] **Timeline view** — For figures with dated speeches (Indira Gandhi), show how stances evolved over time
- [ ] **Export** — Download the full verdict table as CSV/JSON for further analysis

### Infrastructure
- [ ] **Incremental scoring** — Only re-score new chunks; currently deletes all predictions on every run
- [ ] **Versioned snapshots** — Lock a scoring run so the UI can compare `v10-deberta` vs. future models
- [ ] **CI** — Run sanity checks (no unexpected verdict flips) on every new figure ingest

---

## Tech Stack

| Layer | Tech |
|---|---|
| NLI model | `cross-encoder/nli-deberta-v3-large` (HuggingFace, runs locally) |
| Optional LLM | Ollama (llama3.2, mistral, etc.) |
| Backend | FastAPI + SQLite |
| Frontend | React + Vite + TypeScript |
| DB | SQLite (single file `db/whoismyside.db`) |

No cloud API keys required for core scoring. Claude / Anthropic API is not used in the scoring pipeline.
