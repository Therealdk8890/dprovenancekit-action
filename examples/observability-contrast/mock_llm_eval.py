#!/usr/bin/env python3
"""Trivial LLM-eval style check — "answer looks plausible".

No model call. Stdlib heuristics only. PASSes on both baseline and
verify-dropped runs because both still emit ``approved:<claim>``.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LlmEvalResult:
    name: str
    passed: bool
    detail: str


_PLAUSIBLE = re.compile(r"^approved:[A-Za-z0-9_.:-]+$")


def check_plausible(answer: str) -> LlmEvalResult:
    text = (answer or "").strip()
    ok = bool(_PLAUSIBLE.match(text))
    return LlmEvalResult(
        "answer_looks_plausible",
        ok,
        "matches approved:<id>" if ok else f"implausible: {text!r}",
    )


def evaluate(answer: str) -> list[LlmEvalResult]:
    return [check_plausible(answer)]


def all_passed(results: list[LlmEvalResult]) -> bool:
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
