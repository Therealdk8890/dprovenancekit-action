#!/usr/bin/env python3
"""Record baseline + regressed traces for the observability contrast demo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import run_baseline, run_regressed  # noqa: E402
from dprovenancekit import SQLiteTraceStore, TraceQueryDSL, traced_run  # noqa: E402
from dprovenancekit.instrument import TracedEvent  # noqa: E402

DB = Path(__file__).resolve().parent / "demo-traces.sqlite"


def main() -> None:
    for stale in (DB, Path(str(DB) + "-shm"), Path(str(DB) + "-wal")):
        if stale.exists():
            stale.unlink()

    store = SQLiteTraceStore(TracedEvent, str(DB))

    with traced_run(store, context_id="golden"):
        run_baseline()
    with traced_run(store, context_id="baseline"):
        run_baseline()  # same path as golden → path gate PASS
    with traced_run(store, context_id="regressed"):
        run_regressed()  # dropped verify → path gate FAIL

    runs = {r.context_id: r.run_id for r in store.query_runs(TraceQueryDSL())}
    assert set(runs) == {"golden", "baseline", "regressed"}, runs

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"GOLDEN_RUN_ID={runs['golden']}\n")
            fh.write(f"BASELINE_RUN_ID={runs['baseline']}\n")
            fh.write(f"REGRESSED_RUN_ID={runs['regressed']}\n")

    print(
        f"recorded golden={runs['golden']} baseline={runs['baseline']} "
        f"regressed={runs['regressed']} in {DB.name}"
    )


if __name__ == "__main__":
    main()
