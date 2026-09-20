#!/usr/bin/env python3
"""Verification Receipt CI gate (Phase 1B).

Evaluates a VerificationReceipt against a VerificationInvariant using the same
semantics as DProvenanceKit Phase 0 and CaseClarity Phase 1A:

  1. Integrity failure (any of evidence/trace/files_unchanged false) → tampered
  2. Else invariant failure (required_steps / must_include / ordering) → incomplete
  3. Else → verified

JSON Schema validates structure only. This evaluator + integrity flags decide
status. Verified means integrity-protected provenance satisfied the declared
invariant — not that the claim text is objectively true.

Standard library only. Invoked by ``action.yml`` when ``gate-mode=receipt``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Unlikely delimiter for $GITHUB_OUTPUT multiline (heredoc) format.
_DELIM = "__DPROV_RECEIPT_EOF__"

# Canonical step types (do not expand).
_STEP_TYPES = frozenset({"evidence", "extract", "verify", "claim"})
_STATUSES = frozenset({"verified", "incomplete", "tampered"})

# Default vendored invariant relative to this file.
_DEFAULT_INVARIANT = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "verification-receipt"
    / "invariant-claim-path-v1.json"
)


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    reason: str
    invariant_id: str
    integrity_ok: bool
    invariant_ok: bool
    receipt_status_field: str | None
    status_consistent: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _first_index(types: Sequence[str], step: str) -> int | None:
    try:
        return types.index(step)
    except ValueError:
        return None


def evaluate_invariant(
    steps: Sequence[Mapping[str, Any]],
    invariant: Mapping[str, Any],
) -> tuple[bool, str | None]:
    """Return (satisfied, reason) for required_steps / must_include / ordering."""
    types = [str(s.get("type", "")) for s in steps]
    inv_id = str(invariant.get("id", "unknown"))

    required = list(invariant.get("required_steps") or [])
    must_include = list(invariant.get("must_include") or [])
    ordering = list(invariant.get("ordering") or [])

    for step in required:
        if step not in types:
            return (
                False,
                f"Required step type {step} is missing; {inv_id} invariant is not satisfied.",
            )

    for step in must_include:
        if step not in types:
            return (
                False,
                f"must_include step {step} is missing; {inv_id} invariant is not satisfied.",
            )

    for constraint in ordering:
        before = constraint.get("before")
        after = constraint.get("after")
        if before is None or after is None:
            return False, f"Malformed ordering constraint in {inv_id}."
        bi = _first_index(types, str(before))
        ai = _first_index(types, str(after))
        if bi is None:
            return (
                False,
                f"Required step type {before} is missing; {inv_id} invariant is not satisfied.",
            )
        if ai is None:
            return (
                False,
                f"Required step type {after} is missing; {inv_id} invariant is not satisfied.",
            )
        if bi >= ai:
            return (
                False,
                f"Step ordering violated for {inv_id}: {before} must appear before {after}.",
            )

    return True, None


def integrity_passed(integrity: Mapping[str, Any] | None) -> tuple[bool, str | None]:
    """Return (ok, reason) from receipt integrity summary flags."""
    if not isinstance(integrity, Mapping):
        return False, "Receipt is missing integrity summary; treating as tampered."
    evidence = bool(integrity.get("evidence"))
    trace = bool(integrity.get("trace"))
    files_unchanged = bool(integrity.get("files_unchanged"))
    if evidence and trace and files_unchanged:
        return True, None
    failed = []
    if not evidence:
        failed.append("evidence=false")
    if not trace:
        failed.append("trace=false")
    if not files_unchanged:
        failed.append("files_unchanged=false")
    return (
        False,
        "Bound evidence or attestation no longer validates ("
        + ", ".join(failed)
        + ").",
    )


def evaluate_receipt(
    receipt: Mapping[str, Any],
    invariant: Mapping[str, Any],
) -> EvaluationResult:
    """Recompute status from integrity + invariant; do not trust receipt.status blindly."""
    inv_id = str(invariant.get("id") or receipt.get("invariant_id") or "unknown")
    declared = receipt.get("status")
    declared_str = str(declared) if declared is not None else None

    ok_integrity, integrity_reason = integrity_passed(receipt.get("integrity"))
    ok_invariant, invariant_reason = evaluate_invariant(
        list(receipt.get("steps") or []),
        invariant,
    )

    if not ok_integrity:
        status = "tampered"
        reason = integrity_reason or "Integrity check failed."
    elif not ok_invariant:
        status = "incomplete"
        reason = invariant_reason or "Invariant not satisfied."
    else:
        status = "verified"
        reason = "Required steps occurred in order and integrity checks passed."

    # Prefer fixture/projection status_reason when recomputed status matches.
    if declared_str == status and receipt.get("status_reason"):
        reason = str(receipt["status_reason"])

    consistent = declared_str is None or declared_str == status
    return EvaluationResult(
        status=status,
        reason=reason,
        invariant_id=inv_id,
        integrity_ok=ok_integrity,
        invariant_ok=ok_invariant,
        receipt_status_field=declared_str,
        status_consistent=consistent,
    )


def parse_fail_statuses(raw: str | None) -> set[str]:
    if not raw or not str(raw).strip():
        return {"incomplete", "tampered"}
    parts = {p.strip().lower() for p in str(raw).split(",") if p.strip()}
    unknown = parts - _STATUSES
    if unknown:
        raise ValueError(
            f"unknown fail-on-receipt-statuses: {sorted(unknown)}; "
            f"allowed: {sorted(_STATUSES)}"
        )
    return parts


def gate_should_pass(status: str, fail_on: Iterable[str]) -> bool:
    return status not in set(fail_on)


def write_outputs(pairs: Sequence[tuple[str, str]], path: str | None) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in pairs:
            fh.write(f"{key}<<{_DELIM}\n{value}\n{_DELIM}\n")


def render_outputs(result: EvaluationResult, passed: bool) -> list[tuple[str, str]]:
    report = {
        "kind": "verification-receipt",
        "passed": passed,
        "status": result.status,
        "reason": result.reason,
        "invariant_id": result.invariant_id,
        "integrity_ok": result.integrity_ok,
        "invariant_ok": result.invariant_ok,
        "status_consistent": result.status_consistent,
        "receipt_status_field": result.receipt_status_field,
    }
    return [
        ("passed", "true" if passed else "false"),
        ("receipt-status", result.status),
        ("receipt-reason", result.reason),
        ("receipt-invariant-id", result.invariant_id),
        ("report-json", json.dumps(report)),
        ("summary", f"Verification Receipt: {result.status} ({result.invariant_id}) — {result.reason}"),
        # Path-gate outputs left empty / neutral so composite outputs stay defined.
        ("regression-level", "none"),
    ]


def resolve_invariant_path(env: Mapping[str, str]) -> Path:
    raw = (env.get("DPROV_INVARIANT_PATH") or "").strip()
    if raw:
        return Path(raw)
    return _DEFAULT_INVARIANT


def main(env: Mapping[str, str] | None = None) -> int:
    env = dict(os.environ if env is None else env)
    receipt_path = (env.get("DPROV_RECEIPT_PATH") or "").strip()
    if not receipt_path:
        print("error: receipt-path is required when gate-mode=receipt", file=sys.stderr)
        return 2

    try:
        fail_on = parse_fail_statuses(env.get("DPROV_FAIL_ON_RECEIPT_STATUSES"))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    invariant_path = resolve_invariant_path(env)
    try:
        receipt = load_json(receipt_path)
        invariant = load_json(invariant_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: failed to load receipt/invariant: {exc}", file=sys.stderr)
        return 2

    if not isinstance(receipt, dict) or not isinstance(invariant, dict):
        print("error: receipt and invariant must be JSON objects", file=sys.stderr)
        return 2

    result = evaluate_receipt(receipt, invariant)
    if not result.status_consistent:
        print(
            f"warning: receipt.status field is {result.receipt_status_field!r} "
            f"but recomputed status is {result.status!r}; gate uses recomputed status",
            file=sys.stderr,
        )

    passed = gate_should_pass(result.status, fail_on)
    pairs = render_outputs(result, passed)
    write_outputs(pairs, env.get("GITHUB_OUTPUT"))

    summary = next(v for k, v in pairs if k == "summary")
    print(summary)
    step_summary = env.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("### DProvenanceKit Verification Receipt gate\n\n")
            fh.write(f"- **Status:** `{result.status}`\n")
            fh.write(f"- **Invariant:** `{result.invariant_id}`\n")
            fh.write(f"- **Passed:** `{str(passed).lower()}`\n")
            fh.write(f"- **Reason:** {result.reason}\n")

    # Do not exit non-zero on configured fail statuses — action.yml enforces
    # after the PR comment step, matching the path-gate pattern.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
