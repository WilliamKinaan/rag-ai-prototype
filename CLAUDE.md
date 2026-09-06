# CLAUDE.md

Project-specific context for Claude Code sessions on this repo.

## Roadmap

Product roadmap and phase tracker (owners, tasks, status) lives in this
Google Sheet: https://docs.google.com/spreadsheets/d/19mBq97Qhwr4y6phYfIBKrQXxneOMBe8cfAcB76z6o5I/edit?gid=212163437#gid=212163437

It's a single-tab table: `Phase | Objective | Task | Owner | Notes`. Phases
prefixed `[merged]` in both the Phase and Objective columns were done/decided
as of when a session last read the sheet — don't assume that tag is still
accurate without re-checking; re-fetch the sheet rather than trust a cached
summary when a task depends on current phase status.

Rough shape of the roadmap (check the live sheet for current state, this is
just orientation):
- Phase 0 — define scope + evaluation set (categories, reference docs, sample
  contracts, output schema, eval criteria).
- Phase 1 — baseline LLM only: text-based contract review prototype across
  multiple hosted models (OpenAI/Anthropic/Mistral/Gemini), no RAG, baseline
  benchmark. See `plans/phase1-legal-assistant.md` for the build plan and
  scope cuts agreed for this phase (category classification deferred, no
  benchmark harness in that build).
- Phase 2 — add RAG (retrieval over legal reference docs) to the reviewer.
- Phase 3 — RAG-only strict mode (only flag issues supported by retrieved material).
- Phase 4 — lawyer evaluation of all three approaches, architecture decision.
- Phase 5 — working MVP: Google Docs comment integration, persistence,
  privacy/security/observability, controlled pilot deploy.
- Phase 6 — product v1 (auth, workspaces, permissions, ...).

This roadmap is for the **Legal Assistant** feature (contract review). It's
separate from this repo's original RAG demo (UAE-law chat), which predates
the roadmap and isn't tracked in the sheet.

## Planning docs

Feature build plans live under `plans/` (e.g. `plans/phase1-legal-assistant.md`).
When starting work on a roadmap phase, check `plans/` first for an existing
plan before re-deriving one from the sheet.

## Documentation convention

Each significant feature gets its own `CONTEXT-<feature>.md` at repo root
(see `CONTEXT.md` for the core RAG pipeline, `CONTEXT-webapp.md` for the
webapp/chat build, `CONTEXT-deploy-oracle.md` for the live deploy). Write or
update the relevant one when a feature lands; respect explicit scope cuts
noted in the matching plan doc rather than expanding scope silently.

## Deploy

The live instance is a single Oracle Cloud VM, redeployed via
`deploy-oracle.sh`. **Never run that script against the live instance without
asking first** — committing/pushing to GitHub is fine to do freely, but the
actual deploy step always needs explicit confirmation.
