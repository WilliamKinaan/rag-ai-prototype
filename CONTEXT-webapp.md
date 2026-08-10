# Context: Interactive Web Demo (V1.5)

_Last updated: 2026-08-10_
**Status: implemented and smoke-tested locally. Not yet deployed (deployment deliberately deferred — see bottom).**

## Implementation notes (added after building)

All files below exist and a local `uvicorn` run was smoke-tested end to
end (all 4 endpoints + the static page returned correct data, including
a query with playground text — a near-paraphrase playground sentence
correctly scored a lower/more-similar distance than any corpus chunk,
confirming the two distance sources are on the same scale).

One small refactor beyond what's in the original plan: `src/query.py`'s
`retrieve()` was split into `embed → search`, with `search(collection,
query_embedding, k)` pulled out as its own function. The webapp's
`/api/query` needs the raw query embedding (to show its preview) *and*
the search results, and without this split it would've had to embed the
query twice. The CLI (`python src/query.py`) is unaffected — `retrieve()`
still does the same thing, it just calls `search()` internally now.
Re-ran `python src/query.py --eval` after the refactor: still 10/10.

**Next actual step:** user tests it themselves locally
(`uvicorn webapp.app:app --reload --port 8000` from the project root,
then open `http://localhost:8000`). Deployment (Dockerfile, HF Spaces
metadata, `huggingface-spaces` skill) starts only after that, per the
user's explicit scope cut — not started yet.

### Update: split into a query-only landing page + explore page

The single 4-section page was split in two, per the user's request that
the default page be query-only:
- `static/index.html` (+ `static/query.js`) — the new default: just a
  query box and corpus results. No chunking/embedding/storage sections,
  no playground-text comparison.
- `static/explore.html` (+ `static/explore.js`) — the original full
  pipeline demo, unchanged in behavior, reached via a link from the
  landing page ("Curious how this works? Explore the pipeline step by
  step →"), with a "← Back to simple search" link added on it too.
- `static/common.js` — `el`, `postJSON`, `showError`, `renderResultGroup`
  factored out here since both pages need them; load it before the
  page-specific script on both pages.
- `static/script.js` was deleted (its contents now split between
  `common.js` and `explore.js`).

### Update: distance threshold + corpus browser

**Distance threshold filter.** `/api/query` now takes `max_distance`
(default `0.5`, defined once as `DEFAULT_MAX_DISTANCE` in `app.py`) and
drops any result — corpus or playground — with `distance > max_distance`
before returning it, rather than always returning the top-k regardless of
match quality. Both `index.html` and `explore.html` got a number input
(default `0.5`, user-editable) next to the query box, sent as
`max_distance` in the request; the response's now-empty result list is
handled with an explicit "no matches within that distance threshold"
message rather than silently rendering nothing. This directly addresses
the earlier "is it raining today" case — that query now correctly returns
zero results at the default threshold instead of confidently surfacing
the closest-but-irrelevant chunk. Filtering happens server-side, not
client-side, consistent with how playground-distance computation already
works.

**Corpus browser.** Two new endpoints — `GET /api/corpus` (list of
`{source, title}`, title parsed from each doc's first `# ` heading) and
`GET /api/corpus/{source}` (full text of one doc, 404 if unknown). `source`
is matched against an in-memory dict built from `load_documents()` at
startup (`state["docs"]`), not used to touch the filesystem directly, so
there's no path-traversal surface. Two new pages: `static/corpus.html` (+
`corpus.js`) lists every indexed doc as a link; clicking one opens
`static/document.html?source=<filename>` (+ `document.js`) in a new tab,
which fetches and renders that doc's full text. Linked from both
`index.html` (under the query box) and `explore.html` (in the Storage
section). Both new pages carry the same disclaimer banner.

Smoke-tested locally: `/api/corpus`, `/api/corpus/<real file>` (200),
`/api/corpus/<fake file>` (404), `/corpus.html`, `/document.html` all
resolve; threshold filtering verified at 0.1 (filters everything), 0.5
(default, matches prior behavior on a good query), and 2.0 (effectively
unfiltered) — and confirmed the "is it raining today" query now returns
an empty result set at the default threshold.

No backend changes — `app.py`'s existing `StaticFiles(html=True)` mount
serves any named file in `static/` automatically, confirmed working
(`/explore.html`, `/common.js`, `/query.js`, `/explore.js` all 200;
`/script.js` correctly 404s now).

### Update: legal-law corpus pivot + disclaimer banner

Corpus changed to the French/Dutch legal-law theme — see `CONTEXT.md`'s
pivot note for the full rationale and honest eval numbers (hit@1 6/10,
hit@3 10/10; `chroma_db` now has 13 chunks, not 10 — `doc_count`/
`chunk_count` in the Storage section will reflect this automatically,
nothing to change in `app.py`). Two webapp-specific changes that went with
it:
- A prominent disclaimer banner (`.disclaimer` in `style.css`) was added
  to the top of both `index.html` and `explore.html`, above the header —
  "testing prototype, not legal advice, do not rely on this." Both pages'
  query-input placeholders were also updated to a legal-domain example.
- `explore.js`'s `SAMPLE_TEXT` (the prefilled chunking-demo textarea) was
  stale — still the deleted sick-leave policy text. Replaced with an
  excerpt from `netherlands_employment_law.md`.

**Gotcha hit while testing this (for future sessions):** don't start a
second local `uvicorn webapp.app:app` while one is already running — both
processes point at the same on-disk `chroma_db`, and the newer process's
startup event deletes + recreates the collection (`ingest.get_collection`
with `rebuild=True`), which invalidates the *other* process's in-memory
collection reference. Symptom: the already-running server starts
returning `Internal Server Error` on `/api/query` (static pages keep
working fine, since those are read fresh from disk regardless). Fix is
just restarting the affected process. Check `ps aux | grep uvicorn`
before launching another instance for a smoke test.

## Goal

Give the existing V1 CLI pipeline (see `CONTEXT.md`) a visual, shareable web
UI: a button per RAG stage — chunking, embedding, storage, query — so a
visitor can see the mechanics, not just a final answer. Still V1 scope
(semantic search only, no LLM/generation).

## Hosting decision — why not Netlify

Asked about Netlify. Checked Netlify's own docs: Functions there are
stateless/ephemeral — ~1GB memory, ~26s timeout, explicitly "no shared
memory between invocations." A 2.3GB PyTorch model (`bge-m3`) can't stay
loaded across requests under that model; every call would re-download and
re-load it. That rules out Netlify for anything needing the embedding
model loaded once and kept warm.

**Decision: one Hugging Face Space**, Docker SDK. FastAPI backend loads
`BAAI/bge-m3` once at container startup, serves a plain HTML/CSS/JS
frontend from the same app. One deploy, one URL, no CORS, no second
hosting provider. Reuses the already-verified `src/` pipeline code as-is.

## Key decisions

- **Frontend:** plain HTML/CSS/JS, no build step, served as static files
  by the FastAPI app (not Gradio — wanted custom per-stage buttons).
- **Backend:** FastAPI, thin wrapper around existing `src/` modules
  (`config.py`, `loader.py`, `chunking.py`, `embedding.py`, `query.py`'s
  `retrieve()`) — no pipeline logic gets rewritten, only exposed over HTTP.
- **Corpus:** same fixed 6 sample docs from `data/raw/`, re-ingested into a
  fresh `chroma_db` at **container/app startup** (not baked into a Docker
  image) — 10 chunks embeds in seconds once the model is warm.
- **Playground (user-pasted text):** a visitor can paste text into the
  chunking/embedding demo and see it processed live, but it is **never
  added to the corpus/index** (explicitly deferred feature). To avoid a
  silent trap — a visitor pastes text, then queries, and only ever gets
  sample-corpus results without realizing their text wasn't searched —
  the query endpoint also embeds the visitor's current playground text on
  the fly and shows its distance to the query **alongside** the corpus
  results, clearly labeled "your text (not indexed)" vs "sample corpus
  (indexed)." Nothing persists between requests.
- **Model download:** deployment-time concern (Dockerfile, `HF_HOME`
  writable path, `huggingface-spaces` skill) — not relevant for local dev,
  where the model just downloads to the normal local cache like
  `ingest.py` already does.
- **Dependencies:** `webapp/requirements.txt` is separate from the root
  `requirements.txt`. For **local dev on this Mac**, reuse the same
  working pins as the root file (`sentence-transformers==3.3.1`,
  `transformers==4.46.3`, `numpy<2` — see `CONTEXT.md`'s Intel-Mac/torch
  gotcha) plus `fastapi`/`uvicorn`. Those pins are Intel-Mac-specific;
  revisit/loosen them for the Linux Space container at deploy time.

## Architecture

```
rag-prototype/
  src/, data/            unchanged — reused as-is by the webapp
  webapp/
    requirements.txt      webapp-only deps (fastapi, uvicorn + local pins)
    app.py                 FastAPI app: startup loads model + rebuilds
                            chroma_db, mounts static/, defines endpoints
    static/
      index.html            default: query box only
      query.js               landing-page logic (calls /api/query, no playground)
      explore.html            full demo: 4 sections (Chunking, Embedding, Storage, Query)
      explore.js               pipeline-demo logic, incl. playground-text comparison
      common.js               shared helpers used by both pages (el, postJSON,
                               showError, renderResultGroup) — load before the
                               page-specific script
      style.css               shared by both pages
```

`Dockerfile` and Space `README.md` frontmatter are deployment-phase files,
added later via the `huggingface-spaces` skill — not part of the current
implementation pass.

Run locally:
```bash
source rag-env/bin/activate   # or a fresh venv with webapp/requirements.txt
pip install -r webapp/requirements.txt
uvicorn webapp.app:app --reload --port 8000
```
then open `http://localhost:8000`.

## API endpoints

- `GET /api/index-stats` → `{model_name, chunk_size, overlap,
  embedding_dim, doc_count, chunk_count}` — backs the "Storage" section
  with real numbers from the Chroma collection metadata, not hardcoded
  prose.
- `POST /api/chunk` `{text}` → `{chunks: [{index, text, char_count}]}` —
  calls `chunking.chunk_text()` directly. Playground only, not persisted.
- `POST /api/embed` `{texts: [str]}` → `{embeddings: [{text, dim,
  preview: [first 8 floats]}]}` — calls `embedding.embed()`. Preview only
  (not the full 1024-dim vector); full vectors never need to leave the
  server.
- `POST /api/query` `{query, k?, playground_texts?}` → one combined
  response covering the remaining stages in a single round trip:
  ```json
  {
    "query": "...",
    "embedding_dim": 1024,
    "embedding_preview": [/* first 8 floats */],
    "corpus_results": [{"source": "...", "chunk_index": 0, "text": "...", "distance": 0.39}],
    "playground_results": [{"index": 0, "text": "...", "distance": 0.52}]
  }
  ```
  `corpus_results` comes from `retrieve()` against the persisted
  collection, unchanged. `playground_results` (only present if
  `playground_texts` was sent) is computed by embedding those texts fresh
  and taking `1 - cosine_similarity` against the query vector directly —
  same metric as Chroma's `hnsw:space: cosine`, so numbers are directly
  comparable. UI must label this **distance, lower = more similar** —
  never "score" (same convention as the CLI).

## Frontend flow

1. **Chunking** — textarea (prefilled with a sample doc), "Chunk it" →
   `POST /api/chunk` → original text next to numbered chunk cards.
2. **Embedding** — takes chunks from step 1, "Embed it" → `POST
   /api/embed` → dimension + preview values per chunk. Raw texts kept in
   a JS variable for step 4.
3. **Storage** — on page load, `GET /api/index-stats` → shows what's
   actually indexed (doc/chunk counts, model, chunk size).
4. **Query** — input box, "Search" → `POST /api/query` (includes
   playground texts from step 2 if any) → reveals query embedding
   preview, then two labeled result lists (your text vs. sample corpus),
   sorted by ascending distance.

## Scope of the current implementation pass

**Development only.** Build `webapp/` (`requirements.txt`, `app.py`,
`static/`) so it runs and can be tested **locally** via `uvicorn`. No
Dockerfile, no Space README frontmatter, no `huggingface-spaces` skill
invocation, no deployment, no deployment-time verification — those are
deliberately deferred until local testing is done and the user decides to
move on to deployment.

## Next update to this file

Once `webapp/` is built and the user has tested it locally, this file
gets updated to state implementation is done (and later, once deployed,
with the live Space URL).
