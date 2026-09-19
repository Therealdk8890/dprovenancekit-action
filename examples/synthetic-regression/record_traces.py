#!/usr/bin/env python3
"""Record golden / matching / regressed traces for the forkable Action demo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python record_traces.py` from this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import run_golden, run_regressed  # noqa: E402
from dprovenancekit import SQLiteTraceStore, TraceQueryDSL, traced_run  # noqa: E402
from dprovenancekit.instrument import TracedEvent  # noqa: E402

DB = Path(__file__).resolve().parent / "demo-traces.sqlite"


def main() -> None:
    for stale in (DB, Path(str(DB) + "-shm"), Path(str(DB) + "-wal")):
        if stale.exists():
            stale.unlink()

    store = SQLiteTraceStore(TracedEvent, str(DB))

    with traced_run(store, context_id="golden"):
        run_golden()
    with traced_run(store, context_id="candidate"):
        run_golden()  # same path as golden → should PASS the gate
    with traced_run(store, context_id="regressed"):
        run_regressed()  # dropped verify → should FAIL the gate

    runs = {r.context_id: r.run_id for r in store.query_runs(TraceQueryDSL())}
    assert set(runs) == {"golden", "candidate", "regressed"}, runs

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"GOLDEN_RUN_ID={runs['golden']}\n")
            fh.write(f"CANDIDATE_RUN_ID={runs['candidate']}\n")
            fh.write(f"REGRESSED_RUN_ID={runs['regressed']}\n")

    print(
        f"recorded golden={runs['golden']} candidate={runs['candidate']} "
        f"regressed={runs['regressed']} in {DB.name}"
    )


if __name__ == "__main__":
    main()
