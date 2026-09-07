# Context: Legal Assistant (Phase 1 — contract review)

_Last updated: 2026-09-06_
**Status: implemented, not yet smoke-tested against real API keys for
OpenAI/Anthropic (only Mistral has a key configured in this environment).
Rate limiting (per model + per IP) added and verified end-to-end.**

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
Qwen (Alibaba Cloud) was added the same way, outside the sheet's original
four — not on the roadmap, added on direct user request. Gemini is still
listed in the dropdown as "not yet supported" (no existing precedent in
this repo, no key) — picking it gets a clean 400 from `webapp/app.py`
("'gemini' is not yet supported. Choose one of: ...") rather than
pretending it works; the dispatcher pattern makes actually wiring it up
later a matter of one more function + one more registry entry (as Qwen's
addition demonstrated).

Mistral is the **default** selection — not because it's the best output, but
because it's the only provider with a key already configured in this repo's
`.env` (the RAG chat has used it since V2). `ministral-8b-latest` also has
no guaranteed structured-output mode, unlike OpenAI/Anthropic below — its
JSON is prompt-enforced and parsed leniently (strip ` ```json ` fences,
`json.loads`, an unwrap step for a schema-nesting mistake observed in
practice — see `_unwrap_sections()` — then Pydantic validation), and a
parse failure surfaces as a clean 422 ("try a different model") rather than
a 500, since the dropdown makes this a user-selectable outcome.

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
- **Qwen**: no dedicated `dashscope` SDK dependency — reuses the `openai`
  client already installed for OpenAI, pointed at DashScope's
  OpenAI-compatible endpoint, model `"qwen-plus"`.
  `response_format={"type": "json_object"}` is passed (DashScope's
  json_object mode, which requires the literal word "json" somewhere in
  the prompt — already true of the shared schema-hint message) but, like
  Mistral, isn't trusted to enforce the *exact* schema — same
  prompt-enforced + lenient-parse path as Mistral, not OpenAI/Anthropic's
  `.parse()`. **Smoke-tested end-to-end with a live key** — full structured
  review returned correctly.

  Unlike the other three providers, DashScope's compatible-mode host isn't
  one fixed public URL — it's workspace- and region-scoped (e.g. a
  Germany/`eu-central-1` workspace gets its own
  `https://<workspace-id>.eu-central-1.maas.aliyuncs.com/compatible-mode/v1`
  host, shown on the Model Studio console's API Key page next to the key
  itself). `call_qwen_review()` reads that from an optional `QWEN_BASE_URL`
  env var, falling back to the generic international host
  (`dashscope-intl.aliyuncs.com`) if unset — which may or may not work,
  depending on the account/workspace.

`ContractReview`/`ReviewSection`/`Issue` (Pydantic models in
`webapp/legal_review.py`) are the one schema all three providers target.

## Rate limiting: two layers

**Layer 1 — Legal Assistant's own guard, all providers** (`webapp/
legal_rate_limiter.py`, new): at most **2 requests/minute per model** and
**10 requests/30 minutes per client IP**, both in-memory fixed-window
counters (reusing `rate_limiter.py`'s `_FixedWindowLimiter`, one instance
per model name and one per IP, the IP dict never evicted — "simple, good
enough to start" per the brief this was built to). `/api/legal-review`
calls `legal_rate_limiter.reserve(provider, ip)` right after truncating the
extracted text, for every provider. The IP is read via `_client_ip()` in
`webapp/app.py`: prefers Cloudflare's `CF-Connecting-IP` header, then the
`X-Forwarded-For` chain nginx sets (see `CONTEXT-deploy-oracle.md`), then
the raw socket peer as a local-dev fallback. Both `ModelRateLimitExceeded`
and `IPRateLimitExceeded` subclass `rate_limiter.RateLimitExceeded`, so the
existing global `@app.exception_handler(rate_limiter.RateLimitExceeded)`
already turns either into a 429 with a friendly message — no separate
handler needed. Verified end-to-end: tripping the per-model limit, tripping
the per-IP limit across mixed providers, and confirming a different
`X-Forwarded-For` value gets its own independent IP bucket.

**Layer 2 — the shared Mistral key's own budget, Mistral only**
(`webapp/rate_limiter.py`, pre-existing): exists because that key is shared
across three separate live apps in one workspace (see `.env.example`) — a
narrower, unrelated concern from Layer 1. `/api/legal-review` only calls
`rate_limiter.reserve(1)` when `provider == "mistral"`, on top of Layer 1's
check — reserving it unconditionally would reject a Claude/GPT review
because someone used the unrelated RAG chat on Mistral seconds earlier.

The rate-limit badge (`common.js`) is suppressed on `legal.html`: it renders
Layer 2's Mistral-only budget, which is meaningless context on a page where
the active call might be to a different provider entirely. `legal.html`
sets `window.SUPPRESS_RATE_LIMIT_BADGE = true` before loading `common.js`.

**Layer 3 — per-provider daily cap** (`legal_rate_limiter.py`'s
`reserve_daily(provider)`, new): a hard cap on total calls/day, shared
across every visitor, for whichever providers are cost-sensitive enough to
have one — currently **Qwen: 100/day**, **Anthropic: 20/day** (Sonnet 5
runs ~7-10x Qwen-plus's per-token price, so its cap is set tighter for a
comparable dollar-risk, not matched request-for-request — see `DAILY_CAPS`
in `legal_rate_limiter.py`). Layer 1's per-model check is per-*minute* and
resets every window, so it bounds burst rate, not daily spend; this one
doesn't reset until the full 24h window elapses. One dict of per-provider
limits (not a Qwen-specific function, as first built) so a future
provider's cap is a one-line addition to `DAILY_CAPS`, not a new
copy-pasted function+exception pair — `reserve_daily()` is a no-op for any
provider not in that dict (Mistral has Layer 2's shared-key budget
instead; OpenAI has neither). `app.py` calls it unconditionally, right
after the Mistral-only Layer 2 check. `DailyLimitExceeded` subclasses
`rate_limiter.RateLimitExceeded` the same way Layer 1's two exceptions do,
so it gets the same 429 treatment via the existing handler.

Verified directly against the limiter for all four providers (Qwen: 100
reservations succeed, 101st rejected; Anthropic: 20 succeed, 21st
rejected; Mistral/OpenAI: 500 calls each, correctly never rejected by this
layer) plus one real end-to-end smoke test of the Anthropic provider
itself against a live key (full structured review returned correctly,
including catching the contract's undefined "Effective Date" and its
missing governing-law/dispute-resolution boilerplate — issues neither
Mistral nor Qwen flagged in the same side-by-side comparison). Not
smoke-tested via 100/20 real paid calls specifically to trip each cap.

Same caveat as everything else in these two modules: in-memory, resets on
every server restart/deploy — not a substitute for a real spend/quota cap
set directly on each provider's own console (DashScope/Model Studio for
Qwen, the Anthropic Console's prepaid credit balance for Anthropic — the
user is running that as $5 prepaid with auto-reload off, which is itself
a meaningful backstop independent of anything in this file).

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
`UploadFile`/`Form`), `pypdf`, `python-docx`, `anthropic`, `openai`. Qwen
added no new dependency — it reuses the already-installed `openai` package.
`.env.example` gained `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `QWEN_API_KEY`
(each optional — only needed if that dropdown option is actually selected)
plus `QWEN_BASE_URL` (optional — see the workspace-scoped-host note above).

## Known gaps / next steps

- OpenAI's call shape is verified against the installed SDK's method
  signature only, not a live end-to-end call (no key available for it) —
  worth a real smoke test before relying on it in front of anyone else.
  Qwen and Anthropic *have* both been smoke-tested end-to-end against live
  keys (see Layer 3 above) — full structured reviews returned correctly
  for both.
  Qwen model naming moves fast (versioned `qwen3.x-plus`/`-max`/`-flash`
  variants alongside the unversioned `qwen-plus` alias used here) — if
  `call_qwen_review` 400s on an unrecognized model, check
  help.aliyun.com/en/model-studio for current IDs.
- Layer 1's per-IP dict (`legal_rate_limiter.py`) is never evicted — fine
  for a prototype, would need cleanup/expiry before real traffic.
- No contract-category classification, no benchmark harness — both are
  separate sheet tasks, deferred by explicit user request.
- Gemini isn't wired up (no existing precedent/key in this repo).
