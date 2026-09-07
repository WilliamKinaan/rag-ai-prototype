# RAG Prototype — V1: Semantic Search (no LLM)

Ingest → chunk → embed → store → retrieve. No generation yet; this proves
the retrieval half of RAG works before an LLM is wrapped around it.

- **Vector store:** [Chroma](https://www.trychroma.com/), persisted to `./chroma_db/`
- **Embedding model:** [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) via `sentence-transformers`, fully local
- **Chunking:** paragraph-aware packing to ~1000 chars with ~150 char overlap (see `src/chunking.py`)

## Setup

```bash
source rag-env/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Build the index (first run downloads the model, ~2GB)
python src/ingest.py

# Ask a question
python src/query.py "Do I need a notary to set up my company?"

# Check retrieval quality against data/eval.json (hit@1 / hit@3)
python src/query.py --eval
# Note: with only 13 chunks total, hit@3 returns a large fraction of the
# whole index, so a perfect score here would mostly be a smoke test, not a
# statistically meaningful benchmark. Current honest result: hit@1 6/10,
# hit@3 10/10 — the misses are on queries designed to be genuinely hard
# (jurisdiction discrimination without naming the country), not bugs. See
# CONTEXT.md for what the misses reveal about embedding-based retrieval.

# Re-embed everything from scratch (needed after changing config.py)
python src/ingest.py --rebuild
```

## Project layout

```
data/raw/       sample source documents: illustrative English-language
                summaries of French and Dutch law (employment, tenancy,
                company formation) — NOT legal advice, see CONTEXT.md
data/eval.json  (query, expected_source) pairs used by --eval
src/config.py    all tunable constants in one place
src/embedding.py  single embed() used identically by ingest and query
src/chunking.py   paragraph-pack chunker
src/loader.py     reads data/raw/
src/ingest.py     builds/rebuilds the Chroma collection
src/query.py      retrieve(query, k) -> ranked chunks; also --eval mode
```

`retrieve(query, k)` in `src/query.py` is the seam a future generation
(Mistral) layer will wrap — nothing else here assumes an LLM exists.

## Web demo (webapp/)

A FastAPI app wraps this pipeline plus a separate **Legal Assistant**
(contract review) feature — see `CONTEXT-webapp.md` and
`CONTEXT-legal-assistant.md` for the full design/status of each.

```bash
source rag-env/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the API key(s) you need, see below

uvicorn webapp.app:app --reload --port 8000
```

Then open:
- http://localhost:8000/ — landing page
- http://localhost:8000/rag.html — the V1 RAG chat/search/explore demo
- http://localhost:8000/legal.html — Legal Assistant (upload a contract,
  pick a model, get a structured review with a "Download report" button)

**API keys** (`.env`, see `.env.example`): `MISTRAL_API_KEY` powers both the
RAG demo's chat and the Legal Assistant's "Mistral" dropdown option;
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` are only needed for the matching
Legal Assistant dropdown options — leave any of the three blank and just
avoid picking that option (it errors clearly if you do). A quick way to
test the Legal Assistant end-to-end with a free key is Mistral; there's a
sample contract to upload at `samples/sample-contract-with-issues.txt`.

**Fast local startup — `SKIP_RAG_INDEX`:** normal startup loads the ~2GB
`bge-m3` embedding model and encodes the whole corpus before the server
accepts requests (~40-60s on a CPU-only machine). If you're only testing
the Legal Assistant page (it doesn't touch the RAG index at all), skip
that build entirely:

```bash
SKIP_RAG_INDEX=1 uvicorn webapp.app:app --reload --port 8000
```

This brings startup down to ~5-6s. With it set, the RAG demo's pages/API
routes return a clean 503 instead of working — only use it when you don't
need those. It's an inline env var, not read from `.env`, so it can't
accidentally leak into a real deploy; **never set it there**. See
`CONTEXT-webapp.md` for details.
