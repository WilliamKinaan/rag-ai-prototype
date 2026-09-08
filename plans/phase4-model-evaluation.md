# Phase 4: Model Evaluation page (contract-review scorecard)

## Context

Per the roadmap sheet, the user is moving straight to **Phase 4**
("lawyer evaluation of all three approaches, architecture decision") —
skipping ahead of Phases 2/3 build work for now. Phase 4 compares three
distinct approaches to contract review, each from an earlier phase:

- **Phase 1 — baseline LLM only**: call a hosted model directly, no
  RAG. This is what `webapp/legal_review.py`/`/legal.html` already do
  today.
- **Phase 2 — RAG-augmented**: add retrieval over legal reference docs
  to the reviewer. Not built yet.
- **Phase 3 — RAG-only strict mode**: only flag issues supported by
  retrieved material. Not built yet.

Each approach gets its own evaluation later: a set of documents a
lawyer has pre-labeled, run through that approach per provider, scored
against what the lawyer flagged (e.g. "Qwen (qwen-plus): 5 out of 10").
**This build implements only the Phase 1 (baseline/direct-model)
evaluation** — the user's own instruction: don't build Phase 2/3's
evaluation now, but shape the *storage* so each phase's results live
side by side without a schema rewrite when they're added.

The user will supply the lawyer-labeled documents and the actual
scoring logic later ("I will tell you later what happens when someone
clicks"). This build is the scaffolding: the page, the public read of
whatever's stored, and an admin-gated "Evaluate now" action that's a
stub for now — proven to round-trip end to end, same pattern as the
existing `/api/admin/ping` placeholder — so the real runner has
something to plug into without any of this wiring changing later.

Two things the user was explicit about:
- The **page** is public, not admin-gated. Only the **action** behind
  "Evaluate now" is.
- Results must survive a service restart — so a flat file on disk, not
  an in-memory dict (the existing rate limiters are in-memory and
  explicitly documented as reset-on-restart; this is deliberately not
  that pattern).

## Current codebase this builds on

- FastAPI app (`webapp/app.py`), plain static HTML/vanilla JS
  (`webapp/static/`), no templating/build step.
- Contract-review provider registry, `webapp/legal_review.py`:
  `PROVIDERS = {"mistral": ..., "openai": ..., "anthropic": ..., "qwen": ...}`.
  Note `legal.html`'s dropdown also lists `gemini`, but it has **no**
  `PROVIDERS` entry (not yet supported) — the new page must iterate
  `PROVIDERS` only, so Gemini doesn't show up as a phantom row.
- Admin gating (`webapp/cf_access.py`, `CONTEXT-admin-auth.md`):
  `admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(cf_access.require_admin)])`
  in `webapp/app.py` — any route added to it is auto-protected, and
  already covered by the Cloudflare Access Application's existing
  `/api/admin*` wildcard destination (no dashboard change needed for a
  new route under it). Mirror the existing stub exactly:
  ```python
  @admin_router.post("/ping")
  def admin_ping(identity: dict = Depends(cf_access.require_admin)):
      return {"status": "ok", "by": identity["email"]}
  ```
- Landing page `webapp/static/index.html`: `.landing-choices` is a CSS
  grid (`repeat(auto-fit, minmax(260px, 1fr))` in `style.css`) holding
  `.choice-card` links — a third card drops in with no CSS changes.
  Its `.disclaimer` banner currently says "these two demos", which
  becomes stale once a third card exists.
- Flat-file JSON precedent: `data/eval.json` (committed, used by the
  unrelated `src/query.py --eval` RAG benchmark — do not reuse or
  confuse with this feature's file).
- `webapp/static/common.js` provides `$`, `el`, `showError`, plus a
  rate-limit badge gated by `window.SUPPRESS_RATE_LIMIT_BADGE` (already
  set by `legal.html` since that badge tracks Mistral-key budget,
  irrelevant off that page — set it the same way here).

**Important nuance (`CONTEXT-admin-auth.md` §6a):** in production, an
unauthenticated request to `/api/admin/*` through the real hostname
gets a **302 redirect to Cloudflare's login** before it ever reaches
this app. Because the evaluation page itself is public, a visitor's
first-ever click on "Evaluate now" may have no Cloudflare session yet —
that redirect is cross-origin with no CORS headers, so a plain
`fetch()` can't follow it usefully (it throws, or comes back as an
opaque response with `redirect: "manual"`). The frontend needs to
detect that case and point the visitor at `/admin` (a normal page
navigation, which *can* follow the redirect) rather than showing a
generic "request failed" error.

## Changes

**1. `webapp/legal_review.py`** — add next to `PROVIDERS`, single
source of truth for display labels (matches `legal.html`'s existing
dropdown wording):
```python
PROVIDER_LABELS = {
    "mistral": "Mistral (ministral-8b)",
    "openai": "OpenAI (gpt-4o-mini)",
    "anthropic": "Anthropic (Claude Sonnet 5)",
    "qwen": "Qwen (qwen-plus)",
}
```

**2. `webapp/legal_eval.py`** (new) — storage only, no evaluation
logic yet. **Keyed by approach**, so Phase 2/3's evaluations slot in
next to Phase 1's later without touching this shape:
- `APPROACHES = ["baseline", "rag", "rag_only"]` — matches the
  roadmap's Phase 1/2/3 naming (`baseline` = direct model call, no
  RAG; `rag` = RAG-augmented; `rag_only` = RAG-only strict mode). Only
  `"baseline"` has anything wired to it in this build.
- `RESULTS_PATH = PROJECT_ROOT / "data" / "legal_eval_results.json"`
  (new file, distinct from `data/eval.json`; not committed — add to
  `.gitignore`). On-disk shape:
  ```json
  {
    "baseline": {
      "qwen": {"correct": 5, "total": 10, "evaluated_at": "2026-09-08T00:00:00Z"}
    }
  }
  ```
  i.e. `{approach: {provider: {correct, total, evaluated_at}}}` — a
  provider only appears once real scoring has run for that approach;
  `rag`/`rag_only` keys simply won't exist in the file until Phase
  2/3's runners are built and start calling `save_results("rag", ...)`.
- `load_results() -> dict`: read+parse the whole file; missing or
  unparseable → `{}` (no results yet is the normal starting state, not
  an error).
- `save_results(approach: str, results: dict) -> None`: read the
  current file (via `load_results()`), replace just `results[approach]`,
  write the whole thing back via temp-file + `os.replace` (atomic — a
  crash mid-write can't leave a corrupt file, and a future write to
  `"rag"` can't clobber `"baseline"`'s data). Not called by anything
  yet in this build (the stub doesn't write); exists for the real
  Phase 1 runner to call later.
- `get_results_for_display(approach: str = "baseline") -> list[dict]`:
  merges `load_results().get(approach, {})` with
  `legal_review.PROVIDERS`' keys so every known provider gets a row for
  that approach — `{"provider", "label", "evaluated": bool, "correct",
  "total", "evaluated_at"}`, with the last three `None` when not yet
  evaluated. Called with `"baseline"` for now; Phase 2/3 pages/sections
  built later just call it with `"rag"`/`"rag_only"` instead.

**3. `webapp/app.py`**:
- Import `legal_eval`.
- Public endpoint (with the other `/api/*` routes, before the static
  mount; no RAG-index dependency). Takes an `approach` query param so
  Phase 2/3 sections can reuse it later without a new route, but this
  build only ever calls it with `"baseline"`:
  ```python
  @app.get("/api/legal-eval/results")
  def api_legal_eval_results(approach: str = "baseline"):
      if approach not in legal_eval.APPROACHES:
          raise HTTPException(400, f"Unknown approach '{approach}'.")
      return {"approach": approach, "results": legal_eval.get_results_for_display(approach)}
  ```
- Admin-gated stub, added to the existing `admin_router` (inherits
  guarding automatically):
  ```python
  @admin_router.post("/legal-eval/run")
  def admin_run_legal_eval(identity: dict = Depends(cf_access.require_admin)):
      """Stub - mirrors admin_ping. Proves the admin-gated round trip
      from the (public) evaluation page. Only the "baseline" (Phase 1,
      direct-model) approach is wired at all right now - real logic for
      it (run each lawyer-labeled document through legal_review.PROVIDERS,
      score against the lawyer's flags, legal_eval.save_results("baseline", ...))
      is future work, to be specified later. Phase 2/3 ("rag"/"rag_only")
      get their own runners once those approaches exist."""
      return {"status": "ok", "by": identity["email"]}
  ```

**4. `webapp/static/evaluation.html` + `webapp/static/evaluation.js`**
(new, public — lives in `webapp/static/`, not `protected_static/`, so
no explicit FastAPI route is needed for the page itself):
- Reuse existing classes only: `.disclaimer`, `.step`/`.card`,
  `.back-link` — no new design system.
- On load, `evaluation.js` fetches `/api/legal-eval/results` (default
  `approach=baseline`) and renders one row/card per provider:
  `"{label}: {correct} out of {total}"` if evaluated, else `"{label}:
  not yet evaluated"`. Headed e.g. "Direct model calls (baseline)" so
  it's clear this is one of three planned approaches — Phase 2/3
  sections get added the same way later, not built now.
- "Evaluate now" button `POST`s to `/api/admin/legal-eval/run` with
  `redirect: "manual"`. Branches:
  - `res.type === "opaqueredirect"` (or the fetch throws, for the
    cross-origin case without `redirect: "manual"` support) → render
    "Admin sign-in required" with a link to `/admin` (real navigation,
    not fetch, so Cloudflare's redirect flow can actually complete).
  - `res.status === 401` → surface the JSON `detail` message (reachable
    locally where `CF_ACCESS_*` env vars are unset, or via the
    documented raw-IP bypass path).
  - success → show the stub response, re-fetch results (harmless once
    a real runner exists and actually writes something).

**5. `webapp/static/index.html`**:
- Add a third `.choice-card` → `/evaluation.html` ("Model Evaluation").
- Fix `.disclaimer` copy — drop the hardcoded "two demos" count.

**6. `.gitignore`**: add `data/legal_eval_results.json` (generated,
mutable — mirrors why `chroma_db/` is ignored; keeps `deploy-oracle.sh`'s
`git pull` from ever conflicting with a file this app writes at runtime).

## Explicitly out of scope (for this build)

- The real "baseline" evaluation runner (iterating lawyer-labeled
  documents through `legal_review.review_contract()` per provider,
  scoring against the lawyer's flags, calling
  `save_results("baseline", ...)`) — user will specify this later.
- Phase 2 ("rag") and Phase 3 ("rag_only") evaluation entirely — no
  runner, no page section, no UI for them. Only the storage shape
  (`legal_eval.APPROACHES`, results keyed by approach) accounts for
  them existing later.
- The lawyer-labeled dataset's format/location — genuinely unresolved
  (matching a model's free-text flagged passage against a lawyer's
  label isn't a trivial equality check), needs its own design pass.
- Cost/rate guarding for the real runner — once it exists it must go
  through `legal_rate_limiter` the same way `/api/legal-review` does,
  since it will spend real per-provider budget per document per model.
- `CONTEXT-model-evaluation.md` — add once the feature (stub now, real
  runner later) actually lands, per this repo's doc convention.
- Rewiring `legal.html`'s dropdown to source labels from the new
  `PROVIDER_LABELS` dict (cosmetic follow-up, not needed now).

## Verification

1. `SKIP_RAG_INDEX=1 uvicorn webapp.app:app --reload --port 8000`.
2. `/` → third card present, links to `/evaluation.html`, disclaimer no
   longer says "two".
3. `/evaluation.html` unauthenticated → loads with no Cloudflare
   prompt; every `PROVIDERS` key shows "not yet evaluated"; `gemini`
   does not appear.
4. Click "Evaluate now" locally (no `CF_ACCESS_*` set) → 401-with-detail
   branch renders.
5. Manually write `data/legal_eval_results.json` with a `"baseline"`
   key (see on-disk shape above), restart the server, reload → scores
   render as "N out of M" (proves the restart requirement).
6. Once deployed: in a logged-out browser on the real hostname, click
   "Evaluate now" → expect the "Admin sign-in required" / `/admin` link
   branch; sign in; return and click again → expect the stub's
   `{"status": "ok", ...}` success text.
7. `curl -i -X POST http://<raw-ip>:8000/api/admin/legal-eval/run`
   (bypassing Cloudflare) → still 401s, same as the existing
   `admin_ping` check in `CONTEXT-admin-auth.md` §6b.
