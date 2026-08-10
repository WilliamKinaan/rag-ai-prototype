# Context: Interactive Web Demo (V1.5)

_Last updated: 2026-08-10_
**Status: implemented and smoke-tested locally. Static-only deploy live on Netlify (see below). Full backend deployment (Hugging Face Space) blocked/paused — see the Space section further down.**

## Netlify deploy — static frontend only, by explicit choice

Live at `https://rag-ai-prototype.netlify.app/` (GitHub-connected continuous
deployment — pushing to `main` triggers a new Netlify build automatically).

**What works:** the UI shell — all 4 pages, correct CSS/JS, correct look.
**What doesn't:** everything under `/api/*` — search, chunking, embedding,
corpus browsing all 404. This is intentional, not a bug to fix: the
model (`BAAI/bge-m3`, ~2.3GB) cannot run on Netlify Functions (1GB memory
cap — a hard platform ceiling, not a config/timeout issue). The user
explicitly chose to accept a non-functional backend in exchange for the
frontend looking right on Netlify, rather than rearchitecting to either
(a) split hosting (Netlify frontend + backend hosted elsewhere) or
(b) rewrite as fully client-side ML (transformers.js in-browser) — both
discussed and set aside for now.

**Root cause of the original breakage, for the record:** Netlify had no
`netlify.toml`/build config, so it defaulted to publishing the *entire
git repo* as static files, with the repo root as the site root. That's
why `/` 404'd (no `index.html` at repo root) while `/webapp/static/`
found the page — but the page's absolute asset paths (`/style.css`,
`/common.js`, etc., correct for local `uvicorn` where `StaticFiles` is
mounted at app-root `/`) resolved against the wrong root and 404'd too.

**Fix** (`netlify.toml`, repo root):
```toml
[build]
  publish = "webapp/static"
```
This makes Netlify serve `webapp/static/` *as* the site root, which is
exactly what `uvicorn`/FastAPI already does locally — so the fix required
**zero changes to any file under `webapp/static/`**. Same absolute paths,
correct in both places now.

Also removed a stray `runtime.txt` (`3.12`) from an earlier deploy
attempt — a Heroku convention Netlify never uses; it did nothing here and
would have misled a future reader into thinking Netlify runs Python.

**Known follow-up, not yet resolved:** the Netlify site currently has
some form of visitor-access restriction enabled (anonymous requests,
including `curl`, get redirected to a Netlify login page —
`app.netlify.com/edge-access?...`). Check Site settings → Visitor access
in the Netlify dashboard if the demo should be publicly viewable without
a Netlify login.

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

### Update: V2 interactive chat (2026-08-10)

Added an LLM generation layer on top of V1.5's retrieval-only pages.
`CONTEXT.md`'s original V2 plan assumed a locally-run Mistral
(llama.cpp/Ollama) because the dev machine is CPU-only — that's
superseded; this uses the **hosted Mistral AI API**, model
`ministral-8b-latest`, free tier via console.mistral.ai. No local model
weights, no GPU concern, needs a `MISTRAL_API_KEY`.

**Site structure changed:**
- `static/index.html` is now the **chat page** (new default homepage,
  new `chat.js`) — this is the page a first-time visitor lands on.
- The old query-only landing page moved to `static/search.html` /
  `search.js` (was `index.html` / `query.js`), unchanged in behavior.
  Reachable from the chat page's nav row.
- `explore.html` / `corpus.html`'s back-links, which used to say "← Back
  to simple search" and point at `/`, now say "← Back to chat" (still
  `/`, since `/` is the chat page now).

**Backend:** `webapp/llm.py` (new) — no SDK, plain `httpx.post` to
`https://api.mistral.ai/v1/chat/completions` (checked with `pip install
--dry-run mistralai` that even the official SDK wouldn't have disturbed
the pinned `numpy`/`torch`/`transformers`/`pydantic` versions, but
`httpx`/`python-dotenv` were already present in `rag-env` transitively,
so a raw REST call needed zero new heavyweight deps). Reads
`MISTRAL_API_KEY` from a gitignored `.env` (see `.env.example` at repo
root) via `python-dotenv`, **lazily** — the key is only required when
`/api/chat` is actually called, so search/explore/corpus keep working
with no key configured at all.

New endpoint `POST /api/chat` in `app.py`:
```json
// request
{"message": "...", "history": [{"role": "user"|"assistant", "content": "..."}], "k": 3, "max_distance": 0.5}
// response
{"reply": "...", "sources": [{"source": "...", "chunk_index": 0, "text": "...", "distance": 0.39}], "no_context": false}
```
Reuses the same `embed()` + `search()` (from `src/query.py`) and
`DEFAULT_MAX_DISTANCE`/`TOP_K` constants `/api/query` already uses — no
duplicated retrieval logic. Two behaviors worth noting:
- **Retrieval-query concatenation for follow-ups.** A vague follow-up
  like "what about in the Netherlands?" is embedded as `<last user turn
  from history> + " " + message`, not `message` alone, so it still
  retrieves the right chunks instead of falling through to the
  no-context path. (The LLM itself still receives the raw `message`,
  unmodified — only the retrieval embedding uses the concatenation.)
  Smoke-tested locally: without prior history a vague follow-up can
  legitimately clear zero chunks; with a relevant prior turn in
  `history`, retrieval succeeds. In practice, with this corpus's small
  size (13 chunks) and 0.5 default threshold, most reasonably-phrased
  legal-sounding queries clear the threshold even without the fix — the
  concatenation is a robustness safeguard more than something proven to
  fire constantly on this particular corpus.
- **No-context short-circuit.** If zero chunks pass `max_distance`, the
  LLM is never called — a fixed `NO_CONTEXT_REPLY` (`webapp/llm.py`) is
  returned directly, `no_context: true`, `sources: []`. Deterministic,
  costs no API tokens, and doesn't depend on the model choosing to
  refuse. Verified locally (`"what is the capital of France?"` → 200,
  `no_context: true`, no key required).
- **System prompt** (`webapp/llm.py`) instructs the model to answer only
  from the provided context, name its source doc(s), carry the
  "not legal advice" disclaimer into its own replies, and flag it
  explicitly if the retrieved context looks like it's the *wrong
  jurisdiction* for the question — added because `CONTEXT.md` documents
  hit@1 6/10 with France/Netherlands pairs deliberately hard to
  distinguish, so a wrong-country top chunk is a real, expected
  possibility, not a hypothetical.

**Frontend:** `static/chat.js` keeps `history` as a plain in-memory JS
array (cleared on reload, no persistence — matches the rest of the
app's stateless design), sends it with every `/api/chat` call, and
appends the new turn after each response. Sources render via a new
`renderSources()` helper in `common.js` (compact inline tags with the
chunk text as a hover title), next to the existing
`renderResultGroup()` used by the other pages. **Non-streaming** by
explicit choice — full reply after a short wait, not token-by-token —
simpler to build/debug, accepted trade-off over a snappier streaming UI.

**Smoke-tested locally** against the already-running dev `uvicorn`
(no `MISTRAL_API_KEY` set): `/`, `/search.html`, `/explore.html`,
`/corpus.html`, `/search.js`, `/chat.js` all resolve correctly; old
`/query.js` correctly 404s; `/api/chat` returns the deterministic
no-context reply for an off-corpus question with no key needed, and
correctly fails with a clear 500 (`MISTRAL_API_KEY is not set...`) once
retrieval succeeds and it tries to actually call Mistral. **Not yet
tested with a real key** — that needs the user's own free-tier key from
console.mistral.ai, dropped into a local `.env` (`MISTRAL_API_KEY=...`,
gitignored). Also not yet pushed: pushing to `main` auto-deploys
Netlify, which will make the public homepage a chat UI whose only
action 404s (same class of pre-existing issue as `/api/query` there
today, not a new regression, but worth knowing before pushing).

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
  .env                   gitignored; MISTRAL_API_KEY=... (see .env.example)
  webapp/
    requirements.txt      webapp-only deps (fastapi, uvicorn, httpx,
                           python-dotenv + local pins)
    app.py                 FastAPI app: startup loads model + rebuilds
                            chroma_db, mounts static/, defines endpoints
    llm.py                 Mistral API wrapper (system prompt, context
                            formatting, chat-completions call) — used by
                            app.py's /api/chat, no pipeline logic here
    static/
      index.html            default homepage: interactive chat (V2)
      chat.js                 chat-page logic (calls /api/chat, keeps
                               in-memory history)
      search.html            query-only page: chunk search, no LLM
      search.js               search-page logic (calls /api/query)
      explore.html            full demo: 4 sections (Chunking, Embedding, Storage, Query)
      explore.js               pipeline-demo logic, incl. playground-text comparison
      corpus.html             lists every indexed doc
      corpus.js                corpus-list logic (calls /api/corpus)
      document.html           full text of one doc
      document.js              doc-view logic (calls /api/corpus/{source})
      common.js               shared helpers used by every page (el, postJSON,
                               showError, renderResultGroup, renderSources) —
                               load before the page-specific script
      style.css               shared by all pages
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
