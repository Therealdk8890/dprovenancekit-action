#!/usr/bin/env python3
"""Verification Receipt CI gate (Phase 1B + Phase 1C sync).

Evaluates a VerificationReceipt against a VerificationInvariant using the same
semantics as DProvenanceKit Phase 1C (``VerificationReceiptProjector`` /
``VerificationInvariant.evaluate``) and CaseClarity Phase 1A:

  1. Integrity failure (any of evidence/trace/files_unchanged false) → tampered
     (takes precedence over incomplete)
  2. Else invariant failure (required_steps / must_include / ordering) → incomplete
  3. Else → verified

Canonical invariant: ``claim-path-v1``. Reason strings match DPK goldens.

JSON Schema validates structure only. This evaluator + integrity flags decide
status. Verified means integrity-protected provenance satisfied the declared
invariant — not that the claim text is objectively true.

Standard library only. Invoked by ``action.yml`` when ``gate-mode=receipt``.
Does not affect ``gate-mode=path``.
"""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Canonical step types (do not expand).
_STEP_TYPES = frozenset({"evidence", "extract", "verify", "claim"})
_STATUSES = frozenset({"verified", "incomplete", "tampered"})
_MARKDOWN_META = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")

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
                f"Required step type {step} is missing; {inv_id} invariant is not satisfied.",
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
    # Fail closed: only a JSON boolean ``true`` counts as a passing flag. Strings
    # such as "false", numbers, or missing keys must never read as integrity OK.
    evidence = integrity.get("evidence") is True
    trace = integrity.get("trace") is True
    files_unchanged = integrity.get("files_unchanged") is True
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
        reason = (
            "Required steps occurred in the required order and "
            "cryptographic integrity checks passed."
        )

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


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_invariant(invariant: Any) -> str | None:
    """Return an error message when ``invariant`` cannot be evaluated safely.

    An invariant with no constraints would mark every receipt ``verified``, so it
    is rejected (fail closed) instead of silently passing the gate.
    """
    if not isinstance(invariant, Mapping):
        return "invariant must be a JSON object"
    inv_id = invariant.get("id")
    if not isinstance(inv_id, str) or not inv_id.strip():
        return "invariant field 'id' must be a non-empty string"
    for key in ("required_steps", "must_include"):
        value = invariant.get(key, [])
        if value is not None and not _is_string_list(value):
            return f"invariant field {key!r} must be a list of strings"
    ordering = invariant.get("ordering", [])
    if ordering is not None:
        if not isinstance(ordering, list) or not all(
            isinstance(item, Mapping) for item in ordering
        ):
            return "invariant field 'ordering' must be a list of objects"
    if not (
        invariant.get("required_steps")
        or invariant.get("must_include")
        or invariant.get("ordering")
    ):
        return (
            "invariant declares no required_steps, must_include, or ordering "
            "constraints; refusing to evaluate (it would verify any receipt)"
        )
    return None


def validate_receipt(receipt: Any) -> str | None:
    """Return an error message when ``receipt`` is structurally unusable."""
    if not isinstance(receipt, Mapping):
        return "receipt must be a JSON object"
    steps = receipt.get("steps", [])
    if steps is not None and (
        not isinstance(steps, list)
        or not all(isinstance(step, Mapping) for step in steps)
    ):
        return "receipt field 'steps' must be a list of objects"
    integrity = receipt.get("integrity")
    if isinstance(integrity, Mapping):
        for key in ("evidence", "trace", "files_unchanged"):
            if not isinstance(integrity.get(key), bool):
                # Reject rather than reclassify: mapping a malformed flag to
                # "tampered" could pass a job configured to fail only on
                # "incomplete".
                return f"receipt integrity flag {key!r} must be present and a JSON boolean"
    elif integrity is not None:
        return "receipt field 'integrity' must be an object"
    return None


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


def _fresh_delimiter(value: str) -> str:
    """Return a random GitHub output delimiter absent from the value's lines.

    GitHub's multiline output syntax ends a value when a line exactly matches its
    delimiter. Receipt-derived values are untrusted, so a fixed delimiter could let
    a crafted receipt inject forged step outputs such as passed=true.
    """
    lines = value.splitlines()
    while True:
        delimiter = f"ghadelimiter_{secrets.token_hex(16)}"
        if delimiter not in lines:
            return delimiter


def write_outputs(pairs: Sequence[tuple[str, str]], path: str | None) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in pairs:
            value = str(value)
            delimiter = _fresh_delimiter(value)
            fh.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


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
        ("regression-level", "none"),
    ]


def safe_markdown(value: Any) -> str:
    """Render receipt-derived text as inert, single-line Markdown/HTML."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return _MARKDOWN_META.sub(r"\\\1", html.escape(text, quote=True))


def safe_code(value) -> str:
    """Render receipt-derived text as a single inert Markdown code span."""
    text = str(value).replace("\r", " ").replace("\n", " ").replace("`", "'")
    return f"`{text}`"


def render_step_summary(result: EvaluationResult, passed: bool) -> str:
    """Job-summary section; receipt-controlled text is escaped."""
    return (
        "### DProvenanceKit Verification Receipt gate\n\n"
        f"- **Status:** {safe_code(result.status)}\n"
        f"- **Invariant:** {safe_code(result.invariant_id)}\n"
        f"- **Passed:** {str(passed).lower()}\n"
        f"- **Reason:** {safe_markdown(result.reason)}\n"
    )


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

    for error in (validate_receipt(receipt), validate_invariant(invariant)):
        if error is not None:
            print(f"error: {error}", file=sys.stderr)
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
    # Collapse newlines so receipt-controlled text cannot start a workflow
    # command (``::...::``) on its own log line.
    print(summary.replace("\r", " ").replace("\n", " "))
    step_summary = env.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(render_step_summary(result, passed))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
