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
