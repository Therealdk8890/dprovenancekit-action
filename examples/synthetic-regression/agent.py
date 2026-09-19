"""Tiny synthetic agent used only for the CI demo.

Golden path: retrieve → plan → verify → answer
Regressed path: retrieve → answer  (drops plan + verify on purpose)
"""

from __future__ import annotations

from dprovenancekit import record_event, traced


@traced
def retrieve(query: str) -> list[str]:
    return ["policy-doc-1", "claim-evidence-2"]


@traced
def plan(docs: list[str]) -> str:
    return "retrieve-then-verify"


@traced
def verify(claim: str, docs: list[str]) -> bool:
    # Intentional: this step is what compliance cares about.
    return bool(docs)


@traced
def answer(claim: str) -> str:
    return f"approved:{claim}"


def run_golden(claim: str = "loan-applicant-42") -> str:
    docs = retrieve(claim)
    strategy = plan(docs)
    record_event("plan.chosen", {"strategy": strategy})
    ok = verify(claim, docs)
    record_event("verify.result", {"ok": ok})
    return answer(claim)


def run_regressed(claim: str = "loan-applicant-42") -> str:
    # Bug under demo: agent skips planning and verification.
    docs = retrieve(claim)
    return answer(claim)
