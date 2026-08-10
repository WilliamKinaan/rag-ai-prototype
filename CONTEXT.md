# Project Context

_Last updated: 2026-08-10_

## Corpus pivot (2026-08-10): legal-law demo, English only

The original 6-doc corpus (HR policies, a recipe, science, French/Spanish
docs) was replaced with a themed one: 6 English-language documents
summarizing French and Dutch law, 3 topics × 2 jurisdictions (employment,
residential tenancy, company formation) — see `data/raw/`. Every doc opens
with "_Illustrative simplified summary for a search demo — not legal
advice._" so the caveat travels with the text even when a chunk surfaces
out of context. The webapp additionally shows a persistent disclaimer
banner on both pages (`webapp/static/style.css` `.disclaimer`) — this
corpus is explicitly **not to be used for real legal advice or any real
decision**.

Consequence: the "multilingual" justification for `BAAI/bge-m3` (the
cross-lingual eval queries in the original `data/eval.json`) no longer
applies — the corpus is English-only now. Kept `bge-m3` anyway rather than
swapping models, since it still works fine and V1's other design choices
don't depend on multilinguality; just noting the original rationale for
picking it is now partly moot.

Eval queries were redesigned around **jurisdiction discrimination**: each
topic pair (e.g. `france_employment_law.md` vs
`netherlands_employment_law.md`) is deliberately hard to tell apart by
keyword, since a naive query like "notice period under French law" would
trivially win on the word "French" rather than on actual retrieval. Eval
queries instead describe a legal *scenario* using country-specific
institutions/terms of art present in the doc text (e.g. `kantonrechter`,
`huurcommissie`, `notariële akte`, `RCS`) without naming the country.

**Honest result: hit@1 6/10, hit@3 10/10** (not tuned toward 10/10 —
deliberately left as-is per standing guidance not to reword queries until
they pass). The 4 misses are informative, not bugs:
- Two are **negation-sensitivity misses**: a query phrased "can X happen,
  rather than needing Y" surfaces the doc describing Y (the mechanism
  mentioned second/negated) instead of the doc describing X, because
  embeddings match bag-of-meaning proximity, not logical structure. This
  is a real, known limitation of embedding-based retrieval worth having
  hit firsthand.
- Two are genuine close calls between adjacent-topic docs on plain
  paraphrase queries — the correct doc is always in the top 3, just not
  always ranked first.
No fix applied — this is more instructive as a demonstration of retrieval
limits than a saturated eval would have been.

## Goal

Learn how RAG works by building it from scratch (no LangChain/LlamaIndex),
in stages:
- **V1 (done):** semantic search only — ingest, chunk, embed, store,
  retrieve. No LLM.
- **V2 (in progress):** wrap `retrieve()` with a generation layer to
  produce grounded answers. See below — the local-model assumption was
  superseded.
- **Later:** turn the chatbot into an agent.

## Status: V1 complete and verified

Ingestion + retrieval pipeline works end-to-end. Current eval harness
score (legal corpus, see pivot note above): **hit@1: 6/10, hit@3: 10/10**.

## Decisions locked in (V1)

- **Vector store:** Chroma, `PersistentClient`, persisted to `./chroma_db/`
  (gitignored), collection `documents`, `hnsw:space: cosine`.
- **Embedding model:** `BAAI/bge-m3` via `sentence-transformers`, fully
  local/offline. No query-instruction prefix needed (unlike bge-v1.5).
  `normalize_embeddings=True` used for hygiene, though not strictly
  required for correctness under Chroma's cosine space.
- **Chunking:** dependency-free, paragraph-aware packing to ~1000 chars
  with ~150 char overlap; word-boundary fallback for any single paragraph
  too long to fit in one chunk. See `src/chunking.py`.
- **Interface:** CLI scripts (`ingest.py`, `query.py`), no notebook/web UI.
- Single `embed(texts, is_query=False)` function (`src/embedding.py`) used
  identically by both ingest and query, so normalization/prefix handling
  can't silently diverge between the two paths.
- Collection metadata stores `model_name`/`embedding_dim`/`chunk_size`/
  `overlap` at creation; both `ingest.py` and `query.py` assert current
  `config.py` still matches before writing/reading — prevents silently
  garbage rankings after a config change without `--rebuild`. Verified
  this actually fires on mismatch.

## Environment gotcha (important if reinstalling)

This machine is an **Intel Mac (Homebrew `/usr/local`), Python 3.12**, so
PyTorch is capped at **2.2.2** (no newer wheel exists for this
platform/arch) and runs **CPU-only** (no MPS/GPU). Recent
`transformers`/`sentence-transformers` require `torch>=2.4` and break the
import chain on this box. Fix already applied and pinned in
`requirements.txt`:

```
sentence-transformers==3.3.1
transformers==4.46.3
numpy<2
```

This combination was verified to reproduce cleanly from a **fresh venv**
installing only from `requirements.txt` (not just patched by hand in the
working venv) — see `rag-env/`. First run downloads ~2GB of model weights;
expect seconds-per-batch encoding, not instant, since there's no GPU.

**Superseded:** this used to say V2 would run Mistral locally via
llama.cpp/Ollama, since this box is CPU-only. Decision reversed — V2
instead calls the **hosted Mistral AI API** (`ministral-8b-latest`,
free tier via console.mistral.ai), which needs no local model weights
and no GPU. See `CONTEXT-webapp.md`'s "V2 interactive chat" section for
the implementation.

## Project layout

```
data/raw/          6 sample docs (English, legal-law theme — see pivot
                    note above): france_employment_law.md,
                    netherlands_employment_law.md, france_tenant_law.md,
                    netherlands_tenant_law.md, france_company_formation.md,
                    netherlands_company_formation.md
data/eval.json      10 hand-built (query, expected_source) pairs: 6
                    jurisdiction-discrimination scenarios (no country name
                    in the query) + 4 plain paraphrases, designed backwards
                    from the corpus per topic pair
src/config.py       all tunables (paths, model name, chunk size/overlap, k)
src/embedding.py     embed(texts, is_query=False) — shared by ingest+query
src/chunking.py      paragraph-pack chunker + word-boundary fallback
src/loader.py        reads .txt/.md from data/raw/
src/ingest.py        builds/upserts the Chroma collection; --rebuild flag
src/query.py         retrieve(query, k) -> ranked chunks; --eval mode
requirements.txt     pinned versions (see gotcha above)
README.md            usage instructions
chroma_db/          persisted index (gitignored, generated by ingest.py)
rag-env/            python venv (gitignored)
```

## How to resume / verify it still works

```bash
source rag-env/bin/activate
python src/ingest.py          # builds chroma_db/ if missing
python src/query.py --eval    # should print hit@1: 6/10  hit@3: 10/10
```

## Known caveats / non-blocking notes

- The eval set is a smoke test, not a statistically meaningful benchmark:
  13 chunks total means top-3 already covers a large fraction of the whole
  index. Useful for catching regressions when tuning chunking/model
  params, less useful for judging absolute retrieval quality. Grow the
  corpus before trusting the number more.
- The 4 current eval misses are expected/documented (see pivot note
  above) — don't "fix" them by rewording the queries; if hit@1 changes on
  a future run, check whether the corpus or config changed first.
- `_split_by_words` (the long-paragraph fallback in `chunking.py`) rejoins
  words with a single space, so if it ever fires on text that still
  contains a `\n\n` paragraph separator, that separator gets flattened to
  a space in the output chunk. Harmless for retrieval, just not exact
  whitespace round-tripping. Documented in the module docstring.

## V2 status: interactive chat built (2026-08-10)

Generation layer added: `webapp/llm.py` + `POST /api/chat` (see
`CONTEXT-webapp.md`'s "V2 interactive chat" section for the full
design). Reuses `search()`/`embed()` from `src/query.py` unchanged —
`retrieve(query, k)` itself wasn't touched, only wrapped. Not yet
user-verified end-to-end with a real `MISTRAL_API_KEY` (needs the
user's own free-tier key from console.mistral.ai) — the retrieval
path, no-context short-circuit, and missing-key error path were all
smoke-tested locally without one.
