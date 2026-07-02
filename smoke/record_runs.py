#!/usr/bin/env python3
"""Record a golden and a candidate trace for the smoke-test workflow.

Records two identical runs of a tiny instrumented agent into smoke-traces.sqlite,
then exports GOLDEN_RUN_ID / CANDIDATE_RUN_ID to $GITHUB_ENV for the gate step.
"""

import os

from dprovenancekit import SQLiteTraceStore, TraceQueryDSL, record_event, traced, traced_run
from dprovenancekit.instrument import TracedEvent

DB = "smoke-traces.sqlite"


@traced
def retrieve(query):
    return ["doc-1"]


@traced
def verify(claim):
    return True


def one_run(context_id):
    with traced_run(store, context_id=context_id):
        retrieve("smoke question")
        record_event("plan.chosen", {"strategy": "rag"})
        verify("smoke claim")


for stale in (DB, DB + "-shm", DB + "-wal"):
    if os.path.exists(stale):
        os.remove(stale)

store = SQLiteTraceStore(TracedEvent, DB)
one_run("golden")
one_run("candidate")

runs = {r.context_id: r.run_id for r in store.query_runs(TraceQueryDSL())}
assert set(runs) == {"golden", "candidate"}, runs

github_env = os.environ.get("GITHUB_ENV")
if github_env:
    with open(github_env, "a", encoding="utf-8") as fh:
        fh.write(f"GOLDEN_RUN_ID={runs['golden']}\n")
        fh.write(f"CANDIDATE_RUN_ID={runs['candidate']}\n")

print(f"recorded golden={runs['golden']} candidate={runs['candidate']} in {DB}")
