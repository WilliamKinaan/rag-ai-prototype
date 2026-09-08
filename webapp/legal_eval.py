"""Persistence for the Model Evaluation feature's scorecard (Phase 4 on the
roadmap sheet - see plans/phase4-model-evaluation.md).

Stores, per approach and per legal_review.PROVIDERS key, the most recent
evaluation run's score ("N out of M") plus when it ran. Flat JSON file, not
a database - matches this repo's existing convention (see data/eval.json,
an unrelated file used by src/query.py --eval's RAG benchmark - this is a
deliberately separate file).

Results are keyed by "approach" (see APPROACHES below) because the
roadmap's Phase 1/2/3 each get their own contract-review approach, and
therefore their own evaluation, later - baseline (direct model call, no
RAG), RAG-augmented, and RAG-only strict mode. Keeping that dimension in
the storage shape from the start means Phase 2/3's evaluations can be
added later without migrating this file's format. This build only ever
reads/writes the "baseline" approach - the other two exist as reserved
keys with nothing wired to them yet.

The actual evaluation logic - running lawyer-labeled documents through
each provider's contract review and scoring against what the lawyer
flagged - does not exist yet; see plans/phase4-model-evaluation.md's Out
of Scope. This module only defines the storage shape and load/save
helpers so the admin "run" action (webapp/app.py) has somewhere to
eventually write, and the public results endpoint has somewhere to read
from.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from legal_review import PROVIDERS, PROVIDER_LABELS

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Not data/eval.json (that's src/query.py --eval's unrelated RAG benchmark
# file). Gitignored (see .gitignore) - deploy-oracle.sh does `git pull`,
# and a tracked file this app mutates on disk would make that pull fail
# with "local changes would be overwritten" the first time an evaluation
# ever writes to it.
RESULTS_PATH = PROJECT_ROOT / "data" / "legal_eval_results.json"

# Matches the roadmap's Phase 1/2/3 naming (see CLAUDE.md's roadmap
# summary): "baseline" = direct model call, no RAG (Phase 1, what
# legal_review.py already does); "rag" = RAG-augmented reviewer (Phase 2);
# "rag_only" = RAG-only strict mode (Phase 3). Only "baseline" has an
# evaluation wired to it in this build - the other two are reserved keys.
APPROACHES = ["baseline", "rag", "rag_only"]


def load_results() -> dict:
    """{approach: {provider_key: {"correct": int, "total": int,
    "evaluated_at": iso8601 str}}}. Missing file (no evaluation has ever
    run) or an unparseable file (crash mid-write, manual edit) both return
    {} rather than raising - "no results yet" is the normal starting
    state, not an error.
    """
    try:
        return json.loads(RESULTS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_results(approach: str, results: dict) -> None:
    """Replaces just `results[approach]`, leaving every other approach's
    stored data untouched, and writes the whole file back atomically
    (temp file + os.replace) so a crash mid-write can't leave a
    truncated/corrupt file behind - "survives a restart" implies the file
    on disk after any write is always either the old or the new complete
    version, never a partial one.

    Not called by anything yet in this build (the admin "run" stub
    doesn't write) - exists for the real Phase 1 ("baseline") runner to
    call later, and for Phase 2/3 runners once those approaches exist.
    """
    if approach not in APPROACHES:
        raise ValueError(f"Unknown approach '{approach}'. Choose one of: {', '.join(APPROACHES)}")

    data = load_results()
    data[approach] = results

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = RESULTS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(tmp_path, RESULTS_PATH)


def get_results_for_display(approach: str = "baseline") -> list[dict]:
    """Merges load_results()'s data for `approach` with the full, current
    legal_review.PROVIDERS set, so every known provider gets a row even
    before any evaluation has run for it. Order follows PROVIDERS'
    iteration order. (legal.html's dropdown also lists "gemini", but it
    has no PROVIDERS entry yet - it's deliberately excluded here too, so
    it doesn't show up as a phantom "not yet evaluated" row.)
    """
    stored = load_results().get(approach, {})
    rows = []
    for key in PROVIDERS:
        entry = stored.get(key)
        rows.append({
            "provider": key,
            "label": PROVIDER_LABELS.get(key, key),
            "evaluated": entry is not None,
            # .get(), not entry["correct"]: a hand-written/manually-edited
            # results file missing a key should read as "not yet
            # evaluated" for that field, not 500 the whole page.
            "correct": entry.get("correct") if entry else None,
            "total": entry.get("total") if entry else None,
            "evaluated_at": entry.get("evaluated_at") if entry else None,
        })
    return rows
