#!/usr/bin/env python3
"""Mock OTel / LangSmith-style checks — output / HTTP / "trace exists" only.

These deliberately ignore decision-path shape. A run that dropped ``verify``
still PASSes if the final answer looks fine and a fake span was emitted.
Stdlib only; no SaaS.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MockObsResult:
    name: str
    passed: bool
    detail: str


def check_output_nonempty(answer: str) -> MockObsResult:
    ok = bool(answer and str(answer).strip())
    return MockObsResult(
        "output_nonempty",
        ok,
        "answer non-empty" if ok else "empty answer",
    )


def check_http_200(status_code: int = 200) -> MockObsResult:
    ok = int(status_code) == 200
    return MockObsResult(
        "http_200",
        ok,
        f"status={status_code}",
    )


def check_answer_shape(answer: str) -> MockObsResult:
    """Looks like the agent returned a structured approval string."""
    ok = isinstance(answer, str) and answer.startswith("approved:")
    return MockObsResult(
        "answer_shape",
        ok,
        "approved:* prefix" if ok else "unexpected shape",
    )


def check_fake_trace_exists(span_names: list[str] | None = None) -> MockObsResult:
    """Pretend an OTel/LangSmith exporter saw *some* spans — not which ones."""
    spans = span_names or ["retrieve", "answer"]
    ok = len(spans) >= 1
    return MockObsResult(
        "fake_trace_exists",
        ok,
        f"spans={spans}",
    )


def evaluate(answer: str, *, status_code: int = 200, span_names: list[str] | None = None) -> list[MockObsResult]:
    return [
        check_output_nonempty(answer),
        check_http_200(status_code),
        check_answer_shape(answer),
        check_fake_trace_exists(span_names),
    ]


def all_passed(results: list[MockObsResult]) -> bool:
    return all(r.passed for r in results)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    answer = args[0] if args else "approved:loan-applicant-42"
    results = evaluate(answer)
    payload: dict[str, Any] = {
        "passed": all_passed(results),
        "checks": [asdict(r) for r in results],
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
