# Context: Legal Assistant (Phase 1 — contract review)

_Last updated: 2026-09-06_
**Status: implemented, not yet smoke-tested against real API keys for
OpenAI/Anthropic (only Mistral has a key configured in this environment).**

Roadmap source: [the team's phase-tracker sheet](https://docs.google.com/spreadsheets/d/19mBq97Qhwr4y6phYfIBKrQXxneOMBe8cfAcB76z6o5I/edit?gid=212163437#gid=212163437),
Phase 1 ("Baseline LLM only") — see `plans/phase1-legal-assistant.md` for the
full build plan and the row quoted from the sheet.

## What this is

A second demo alongside the existing UAE-law RAG chat, reachable from a new
landing page (`/`) with two entry points: **RAG Demo** (unchanged, moved to
`/rag.html`) and **Legal Assistant** (`/legal.html`, new). Upload a contract
(PDF/DOCX/TXT/MD), pick a model from a dropdown, get back a structured
review: **section → flagged passage → suggested fix**. No RAG involved —
this is deliberately the sheet's baseline-LLM-only phase.

**Explicitly out of scope for this pass** (per the sheet + user's own scope
cut): contract category/type classification, benchmark evaluation/scorecard,
any retrieval. All to be revisited in a later phase.

## Site restructuring

`index.html` used to *be* the chat demo. It's now the landing page; the old
chat markup moved verbatim to `rag.html`. `search.html`/`explore.html`/
`corpus.html`'s "← Back to chat" link now points to `/rag.html` instead of
`/` — those three pages are RAG-demo-only tools, so they should return to the
chat, not the new fork-in-the-road landing page.

## Why a provider dropdown

The sheet's Phase 1 explicitly asks to "test multiple hosted models
(OpenAI/Anthropic/Mistral/Gemini)". Rather than hardcode one, `legal.html`
exposes a dropdown, and `webapp/legal_review.py` has one call function per
provider behind a single `review_contract(provider, text)` dispatcher.
Gemini isn't wired up (no existing precedent in this repo, no key), but the
dispatcher pattern makes adding it later a matter of one more function + one
more registry entry.

Mistral is the **default** selection — not because it's the best output, but
because it's the only provider with a key already configured in this repo's
`.env` (the RAG chat has used it since V2). The UI says so explicitly, since
a demo whose default option produces the weakest output would otherwise read
as a bug. `ministral-8b-latest` also has no guaranteed structured-output
mode, unlike OpenAI/Anthropic below — its JSON is prompt-enforced and parsed
leniently (strip ` ```json ` fences, `json.loads`, then Pydantic validation),
and a parse failure surfaces as a clean 422 ("try a different model") rather
than a 500, since the dropdown makes this a user-selectable outcome.

## Structured output, per provider

- **OpenAI** (`anthropic`-style official SDK, not raw `httpx` — no prior
  OpenAI code in this repo to match, and an official SDK with real
  JSON-schema-constrained output beats prompt-and-hope):
  `client.chat.completions.parse(model="gpt-4o-mini", ..., response_format=ContractReview)`
  → `response.choices[0].message.parsed`. Verified against the installed
  `openai==3.8.0` by introspecting the method signature (no live key
  available in this environment to smoke-test end-to-end).
- **Anthropic**: `client.messages.parse(model="claude-sonnet-5", ...,
  output_format=ContractReview)` → `response.parsed_output`. Verified the
  same way against installed `anthropic==1.4.0` — `output_format` on
  `.parse()` internally builds the `output_config={"format": {"type":
  "json_schema", ...}}` request shape.
- **Mistral**: no SDK, raw `httpx` matching `webapp/llm.py`'s existing style
  and reusing its `MISTRAL_API_URL`/`MISTRAL_MODEL_NAME` constants. Schema is
  prompt-enforced only (see above).

`ContractReview`/`ReviewSection`/`Issue` (Pydantic models in
`webapp/legal_review.py`) are the one schema all three providers target.

## Rate limiting: Mistral-only, on purpose

`webapp/rate_limiter.py`'s in-memory budget exists because the Mistral key
is shared across three separate live apps in one workspace (see
`.env.example`) — it is this app's *share* of that shared quota, nothing
more general. `/api/legal-review` only calls `rate_limiter.reserve(1)` when
`provider == "mistral"`. Reserving it unconditionally would mean a Claude or
GPT contract review could get rejected because someone used the unrelated
RAG chat on Mistral seconds earlier, surfaced as a confusing
Mistral-flavored 429. OpenAI/Anthropic calls go out with no local rate/cost
guard for now — a known phase-1 gap, not an oversight.

The rate-limit badge (`common.js`) is also suppressed on `legal.html` for
the same reason: it renders the Mistral-only budget, which is meaningless
context on a page where the active call might be to a different provider
entirely. `legal.html` sets `window.SUPPRESS_RATE_LIMIT_BADGE = true` before
loading `common.js`.

## File parsing

`webapp/legal_review.extract_text()` dispatches on the upload's file
extension: `.txt`/`.md` decode as UTF-8 directly, `.pdf` via `pypdf`
(`PdfReader`, join `page.extract_text()`), `.docx` via `python-docx`
(`Document`, join paragraph text). An unrecognized extension raises
`ValueError` before any parsing work, which the endpoint turns into a 400.
Extracted text is capped at `MAX_CHARS` (~60k chars, roughly 20-30 pages);
longer documents are truncated with a `truncated: true` flag threaded all
the way to `legal.html`, which renders a visible notice rather than
silently dropping content.

## New dependencies

`webapp/requirements.txt` gained `python-multipart` (required for FastAPI's
`UploadFile`/`Form`), `pypdf`, `python-docx`, `anthropic`, `openai`.
`.env.example` gained `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` (each optional —
only needed if that dropdown option is actually selected).

## Known gaps / next steps

- OpenAI and Anthropic call shapes are verified against the installed SDK's
  method signatures, not a live end-to-end call (no API keys available in
  this environment when built) — worth a real smoke test with actual keys
  before relying on this in front of anyone else.
- No rate/cost guard on OpenAI/Anthropic calls (see above).
- No contract-category classification, no benchmark harness — both are
  separate sheet tasks, deferred by explicit user request.
- Gemini isn't wired up (no existing precedent/key in this repo).
