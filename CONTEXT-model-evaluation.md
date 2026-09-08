# Context: Model Evaluation (Phase 4 — scorecard scaffolding)

_Last updated: 2026-09-08_
**Status: scaffolding implemented — page, public results endpoint, and an
admin-gated "Evaluate now" stub all wired end-to-end. No real evaluation
logic exists yet; see "What's deliberately not built" below.**

Roadmap source: [the team's phase-tracker sheet](https://docs.google.com/spreadsheets/d/19mBq97Qhwr4y6phYfIBKrQXxneOMBe8cfAcB76z6o5I/edit?gid=212163437#gid=212163437),
Phase 4 ("lawyer evaluation of all three approaches, architecture
decision") — see `plans/phase4-model-evaluation.md` for the full build
plan. Built directly, skipping ahead of Phase 2 (RAG-augmented reviewer)
and Phase 3 (RAG-only strict mode), which aren't implemented yet.

## What this is

A third public page, `/evaluation.html` (linked from the landing page
alongside RAG Demo and Legal Assistant), showing a per-provider scorecard
for the Legal Assistant's contract review — e.g. "Qwen (qwen-plus): 5 out
of 10" — meaning how many of a fixed, lawyer-labeled set of documents that
model's review agreed with on what the lawyer had already flagged.

The page itself is **not** admin-gated (the user was explicit about this).
Only the **action** behind its "Evaluate now" button is: it `POST`s to
`/api/admin/legal-eval/run`, joined to the existing `admin_router` in
`webapp/app.py` the same way `/api/admin/ping` is, so it inherits
Cloudflare Access protection automatically (see `CONTEXT-admin-auth.md`).

## Why results are keyed by "approach", not just provider

The roadmap's Phase 1/2/3 are three distinct ways of doing contract
review — baseline direct-model call (Phase 1, what's built today),
RAG-augmented (Phase 2), RAG-only strict mode (Phase 3) — and Phase 4 asks
to evaluate all three against each other. Each will eventually get its
own lawyer-labeled evaluation and its own scores per provider. Rather than
build storage for only Phase 1 and reshape it twice later,
`webapp/legal_eval.py`'s results file is keyed by approach from the start:

```json
{
  "baseline": {
    "qwen": {"correct": 5, "total": 10, "evaluated_at": "2026-09-08T00:00:00Z"}
  }
}
```

`legal_eval.APPROACHES = ["baseline", "rag", "rag_only"]` — only
`"baseline"` has anything wired to it right now. Adding Phase 2/3's
evaluation later is a matter of a new runner calling
`save_results("rag", ...)` / `save_results("rag_only", ...)` and a new
page section calling `get_results_for_display("rag")` — no migration of
existing data, matching how `webapp/legal_review.py`'s `PROVIDERS`
registry made adding Qwen a pure addition rather than a rewrite.

## Storage: why a flat file, not memory

The user was explicit that results must survive a service restart — the
existing rate limiters (`rate_limiter.py`, `legal_rate_limiter.py`) are
in-memory and documented as reset-on-restart; this is deliberately not
that pattern. `webapp/legal_eval.py` reads/writes
`data/legal_eval_results.json` (distinct from `data/eval.json`, an
unrelated file used by `src/query.py --eval`'s RAG benchmark). Writes go
through a temp-file-plus-`os.replace` so a crash mid-write can't leave a
truncated file behind. The file isn't committed (`.gitignore`d) since it's
generated/mutable output, not source — a tracked file this app mutates at
runtime would make `deploy-oracle.sh`'s `git pull` fail the first time a
real evaluation ever wrote to it.

## The Cloudflare Access redirect nuance

Unlike `/legal.html` or `/admin` (both already behind Access by the time
any privileged action fires from them), `/evaluation.html` is public — so
a visitor's first-ever click on "Evaluate now" may have no
`CF_Authorization` cookie yet. Per `CONTEXT-admin-auth.md` §6a, an
unauthenticated hit on `/api/admin/*` through the real hostname gets a
**302 redirect to Cloudflare's login**, cross-origin with no CORS headers
— a plain `fetch()` can't follow that usefully. `evaluation.js` calls the
endpoint with `redirect: "manual"` and treats `res.type ===
"opaqueredirect"` (or a thrown error, depending on the browser) as "not
signed in", pointing the visitor at `/admin` via a real page navigation
instead — that's the one thing that *can* complete Cloudflare's redirect
flow, since a fetch is explicitly not allowed to.

## What's deliberately not built

- **The real "baseline" evaluation runner.** Iterating the lawyer-labeled
  document set through `legal_review.review_contract()` per provider,
  scoring the result against the lawyer's flags, and calling
  `legal_eval.save_results("baseline", ...)` — none of this exists.
  `admin_run_legal_eval()` in `webapp/app.py` is a stub (mirrors
  `admin_ping`) that proves the admin-gated round trip and nothing else.
  The user will specify the actual scoring approach later.
- **The lawyer-labeled dataset itself** — format and storage location are
  unresolved. Matching a model's free-text flagged passage against a
  lawyer's label isn't a trivial equality check; this needs its own
  design pass once real documents are shared.
- **Phase 2 ("rag") and Phase 3 ("rag_only") evaluation** — no runner, no
  page section, no UI. Only the storage shape accounts for them.
- **Cost/rate guarding for the real runner.** Once it exists, it will
  spend real per-provider budget once per document per model and must go
  through `legal_rate_limiter` the same way `/api/legal-review` does —
  not done here since there's no runner yet to guard.
- Rewiring `legal.html`'s dropdown to source its labels from the new
  `legal_review.PROVIDER_LABELS` dict (cosmetic, unrelated to this
  feature's own function).

## Files

- `webapp/legal_review.py` — added `PROVIDER_LABELS`, next to `PROVIDERS`.
- `webapp/legal_eval.py` (new) — `APPROACHES`, `load_results()`,
  `save_results(approach, results)`, `get_results_for_display(approach)`.
- `webapp/app.py` — `GET /api/legal-eval/results?approach=` (public),
  `POST /api/admin/legal-eval/run` (admin-gated stub, on `admin_router`).
- `webapp/static/evaluation.html` + `evaluation.js` (new, public — plain
  static files, no protected-route wrapper needed for the page itself).
- `webapp/static/index.html` — third `.choice-card`; disclaimer copy no
  longer hardcodes "two demos".
- `.gitignore` — `data/legal_eval_results.json`.
- `CONTEXT-admin-auth.md` — route table + a note on the new stub.
