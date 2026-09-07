# Phase 1: Legal Assistant (contract review)

## Source

Roadmap sheet: https://docs.google.com/spreadsheets/d/19mBq97Qhwr4y6phYfIBKrQXxneOMBe8cfAcB76z6o5I/edit?gid=212163437#gid=212163437

Relevant row from that sheet, quoted for reference (phases before/after this
one were marked `[merged]` — already done or superseded — at the time this
plan was written):

| Phase | Objective | Task | Owner | Notes / Recommendation |
|---|---|---|---|---|
| Phase 1 | Baseline LLM only | Build contract category classifier | William | |
| Phase 1 | Baseline LLM only | Build text based contract review prototype using hosted LLM APIs | William | No RAG, no UI polish. Focus only on review quality. The output is also the categories of the contract |
| Phase 1 | Baseline LLM only | Test multiple hosted models | William | Comparable results for OpenAI / Anthropic / Gemini or other selected models |
| Phase 1 | Baseline LLM only | Run benchmark evaluation | William | Baseline scorecard for each model |
| Phase 1 | Baseline LLM only | Review output and share feedback | Wesam | |

Later phases (2-5, all `[merged]` i.e. planned-but-not-current) layer RAG onto
this baseline, then a strict RAG-only mode, then lawyer evaluation, then a
working MVP (Google Docs comment integration, persistence, deploy). None of
that is in scope here — this plan is Phase 1 only: no RAG, no persistence, no
Google Docs integration.

## What the user actually asked for

A new landing page with two entry points:
- **"RAG demo"** → today's existing chat page (unchanged).
- **"Legal assistant"** → new: upload a contract file, pick a model, get back
  a structured review shaped as **section → flagged text in that section →
  suggested fix**, from the model.

Decisions confirmed with the user (2026-09-06):
- **Model is a dropdown** (Mistral / OpenAI / Anthropic), not a single fixed
  choice — this doubles as the sheet's "test multiple hosted models" task.
- **Upload accepts PDF + DOCX + TXT/MD** (real contracts are rarely plain text).
- **Contract category classification is explicitly deferred** — the sheet
  asks for it, but the user said skip it for now, do it later. Output stays
  strictly section → text → suggestion.
- Benchmark evaluation / scorecard (sheet's later Phase 1 tasks) is also not
  part of this build — this plan only covers the prototype + UI itself.

## Current codebase (as of this plan)

Single FastAPI app (`webapp/app.py`) serving plain static HTML/JS
(`webapp/static/`, no framework/build step) plus a small framework-free RAG
pipeline (`src/`). One existing LLM integration: `webapp/llm.py` calls
Mistral via raw `httpx` (no SDK, "no framework wrappers" house style),
gated by an in-memory rate limiter (`webapp/rate_limiter.py`) sized for the
*shared* Mistral key (see `.env.example` — the same key backs two other
apps in the workspace). No file upload exists anywhere; no PDF/DOCX parsing
dependency; no structured/JSON-mode LLM output anywhere in the repo.

Docs convention already in place: `CONTEXT.md` (core pipeline),
`CONTEXT-webapp.md` (webapp build log), `CONTEXT-deploy-oracle.md` (live
deploy). This feature gets its own `CONTEXT-legal-assistant.md` on the same
pattern once built.

## Site structure changes

`/` (`webapp/static/index.html`) is currently the chat demo. It becomes the
new two-button landing page; the current chat markup moves out to a new
`rag.html` so nothing is lost, just relocated:

- `webapp/static/index.html` (rewritten) — landing page, two link-cards:
  "RAG Demo" → `/rag.html`, "Legal Assistant" → `/legal.html`. Reuse the
  existing `.step`/card visual language in `style.css`, not a new design system.
- `webapp/static/rag.html` (new) — today's `index.html` content verbatim
  (disclaimer, chat UI, nav links to search/explore/corpus). Loads the
  existing `common.js` + `chat.js` unchanged.
- `webapp/static/search.html`, `explore.html`, `corpus.html` — update the
  `<a href="/">← Back to chat</a>` back-link to `href="/rag.html"` (3
  one-line edits). `document.html` has no such link, leave it.
- `webapp/static/legal.html` (new) + `webapp/static/legal.js` (new) — the
  legal-assistant page (below).
- `webapp/static/style.css` — add landing-page card styles and legal-review
  result styles (section/issue cards), reusing existing tokens
  (`--panel`/`--border`/`.step`/`.card`), not new ones.

## Backend

### New module: `webapp/legal_review.py`

- Pydantic models: `Issue {text, suggestion}`, `ReviewSection {section,
  issues: list[Issue]}`, `ContractReview {sections: list[ReviewSection]}`.
- `MAX_CHARS` cap (~60,000 chars) on extracted text; if exceeded, truncate
  and surface a `truncated: bool` flag through to the response.
- `extract_text(filename: str, content: bytes) -> str`: dispatch on
  `Path(filename).suffix.lower()`:
  - `.txt`/`.md` → decode UTF-8 directly
  - `.pdf` → `pypdf` (`PdfReader`, join `page.extract_text()`)
  - `.docx` → `python-docx` (`Document`, join paragraph text)
  - anything else → raise `ValueError` (endpoint turns this into a 400,
    *before* any parsing work)
- One review-prompt template shared by all providers: return **only** JSON
  matching the schema above, reviewing the contract for clauses/passages a
  lawyer should look at, with a suggested fix per issue.
- Per-provider call functions, each returning a validated `ContractReview`:
  - `call_mistral_review(text)` — reuse the `MISTRAL_API_URL`/`MISTRAL_API_KEY`
    pattern from `webapp/llm.py` (plain `httpx`, matching that file's
    existing style). `ministral-8b-latest` has no guaranteed JSON mode —
    prompt-enforce the schema, then parse leniently (strip ` ```json `
    fences, `json.loads`, `ContractReview.model_validate`). **On parse
    failure, return a clear 4xx-style error** ("the selected model didn't
    return valid JSON — try a different model"), not a raw 500, since the
    dropdown makes this a user-selectable outcome.
  - `call_openai_review(text)` — official `openai` SDK (no prior OpenAI code
    in this repo; use the SDK, not raw HTTP). Use OpenAI's JSON-schema
    structured-output response format with the `ContractReview` schema.
    **Verify the exact call shape against the installed `openai` package
    version before wiring the endpoint** — don't hardcode a guessed method
    name from memory.
  - `call_anthropic_review(text)` — official `anthropic` SDK. Model ID:
    `claude-sonnet-5`. Use the raw-schema structured-output shape:
    ```python
    response = client.messages.create(
        model="claude-sonnet-5", max_tokens=16000,
        messages=[...],
        output_config={"format": {"type": "json_schema", "schema": {...}}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    ```
    (Not `output_format=PydanticModel` — that shortcut appears in one SDK
    doc example but the same doc's own front matter flags it as deprecated;
    the raw-schema `output_config` form is the one to trust.)
  - `PROVIDERS = {"mistral": ..., "openai": ..., "anthropic": ...}` registry
    mapping dropdown value → call function + required env var name, plus
    `review_contract(provider, text) -> ContractReview` dispatcher that
    raises a clear "X_API_KEY is not set" error on a missing key (mirroring
    `llm.call_mistral`'s existing message style).

  **Before wiring the endpoint:** run `pip show anthropic openai` in the
  `webapp` venv and do one throwaway smoke call per new provider (scratchpad,
  not committed) to confirm the actual call shape/return type on the
  installed version — don't wire three unverified SDK calls straight into
  the endpoint.

### `webapp/app.py`

New endpoint:
```python
@app.post("/api/legal-review")
async def api_legal_review(file: UploadFile = File(...), provider: str = Form(...)):
```
- Validate `provider` against `legal_review.PROVIDERS` (400 if unknown).
- Validate the filename extension via `legal_review.extract_text` (400 on
  `ValueError`, before any heavy parsing).
- **Rate limiting: reserve only when `provider == "mistral"`.** The existing
  `rate_limiter` budgets this app's *share of the shared Mistral key* (see
  `.env.example`) — it has nothing to do with OpenAI/Anthropic quota, and
  reserving unconditionally would reject a Claude/GPT contract review
  because someone used the RAG chat on Mistral seconds earlier, with a
  Mistral-flavored error message. Skip the limiter entirely for the other
  two providers (documented as a phase-1 gap — no cost guard on those yet).
- Map missing-key/config errors to 500, upstream API errors to 502,
  JSON-parse failures (Mistral) to 422 with the friendly message above.
- Return `{"provider": provider, "truncated": bool, "review": {...}}`.

### `webapp/requirements.txt`

Add: `python-multipart` (required for `UploadFile`/`Form`), `pypdf`,
`python-docx`, `anthropic`, `openai`.

### `.env.example`

Add `OPENAI_API_KEY=` and `ANTHROPIC_API_KEY=` blocks, same comment style as
the existing `MISTRAL_API_KEY` entry — note each is optional per-provider;
the dropdown option simply errors clearly if its key is unset.

## Frontend: `webapp/static/legal.html` + `legal.js`

- Disclaimer banner specific to contract review (not legal advice, prototype,
  don't rely on it for real decisions) — same visual style as the existing
  banner, different copy.
- Form: file input (`accept=".txt,.md,.pdf,.docx"`), a `<select>` for
  provider (Mistral / OpenAI / Anthropic — **default to Mistral**, the only
  key guaranteed configured out of the box; note in a code comment that
  Mistral's smaller model is also the weakest link for schema-faithful JSON,
  so this is a "works by default" choice, not a quality endorsement),
  "Analyze" button with a loading state (contract review can take 10-30s).
- On response, render each `review.sections[i]` as a card: section name as
  heading, then each `issues[j]` as a sub-item showing the flagged text and
  the suggestion. Render `truncated: true` as a visible notice above the
  results (not just received and dropped).
- Reuse `common.js`'s `$`/`el`/`showError` helpers; use `FormData` + a direct
  `fetch` (multipart, not `postJSON`'s JSON body) for the upload, matching
  how `document.js` already fetches directly (per `common.js`'s own comment
  on that pattern).
- **Suppress the rate-limit badge on this page.** `common.js` unconditionally
  injects a "requests left" badge sourced from the Mistral-only budget — on
  a page where the user may be calling OpenAI or Anthropic, that badge is
  misleading. Add a `window.SUPPRESS_RATE_LIMIT_BADGE` check at the top of
  `_injectRateLimitBadge()` in `common.js` (skip injection + the one-shot
  status fetch), set that flag in an inline `<script>` in `legal.html` before
  `common.js` loads. Only change to `common.js`.
- Small nav link back to `/` ("← Back to home").

## Documentation

Add `CONTEXT-legal-assistant.md` at repo root (matching the existing
`CONTEXT*.md` convention, closest sibling `CONTEXT-webapp.md`): what was
built, the provider-dropdown design, file-parsing choices, the rate-limiter
carve-out for non-Mistral providers, and the deferred category
classification (explicitly out of scope, why, link back to this plan/sheet).

## Out of scope (explicit)

- Contract category/type classification (user said defer to later).
- Any RAG involvement in the legal-review path (sheet's Phase 1 is
  baseline-LLM-only, no retrieval — that's Phase 2+ on the sheet).
- Benchmark evaluation / model scorecard (separate sheet task, not this build).
- Rate/cost guarding for OpenAI/Anthropic calls (documented gap, not fixed here).
- Deploying to Oracle — commit/push only; `deploy-oracle.sh` is run only on
  explicit user confirmation, per existing project convention.

## Verification

1. `uvicorn webapp.app:app --reload --port 8000` locally.
2. Visit `/` → confirm both landing buttons route correctly; confirm
   `/rag.html` still behaves exactly like the old chat page; confirm the
   three back-links from search/explore/corpus land on `/rag.html`.
3. On `/legal.html`, upload a small sample `.txt` contract with Mistral
   selected (works out of the box with the existing key) → confirm the
   section/issue/suggestion structure renders, and that a deliberately huge
   file shows the truncation notice.
4. Set `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` locally and repeat with each
   provider selected → confirm real structured output comes back (this is
   where the pre-wiring SDK smoke test pays off).
5. Confirm a bad file extension (e.g. `.png`) returns a 400 with a clear
   message, and an unset provider key returns a clear 500, not a stack trace.
