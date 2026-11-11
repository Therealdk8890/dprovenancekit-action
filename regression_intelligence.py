"""Deterministic normalization of the SDK regression report.

This module does not compare traces or re-evaluate gate policy. It converts the
engine's structured steps_by_change output into a versioned CI finding envelope.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from typing import Any, Mapping

_SCHEMA_VERSION = "dpk.regression-intelligence.v1"
_CHANGE_ORDER = ("removed", "added", "reordered", "ambiguous", "semanticMatch")
_CHANGE_DEFINITIONS = {
    "removed": ("STEP_REMOVED", "divergence", "Step is present in the baseline but absent from the candidate."),
    "added": ("STEP_ADDED", "divergence", "Candidate contains a step not mapped to the baseline."),
    "reordered": ("STEP_REORDERED", "divergence", "Step order differs from the baseline."),
    "ambiguous": ("AMBIGUOUS_ALIGNMENT", "divergence", "The engine could not establish an unambiguous match."),
    "semanticMatch": ("SEMANTIC_EQUIVALENCE_ACCEPTED", "accepted_equivalence", "The configured evaluator accepted the changed step as equivalent."),
}
_MARKDOWN_META = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


def _required_string(report: Mapping[str, Any], key: str) -> str:
    value = report.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"gate report field {key!r} must be a non-empty string")
    return value


def _safe_cell(value: Any) -> str:
    """Render untrusted trace-derived text as inert content in Markdown tables."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return html.escape(text, quote=True).replace("|", "&#124;").replace("`", "&#96;")


def _safe_inline(value: Any) -> str:
    """Escape untrusted text so it cannot add Markdown structure or HTML."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return _MARKDOWN_META.sub(r"\\\1", html.escape(text, quote=True))


def build_intelligence(report: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize engine findings; never re-align traces or recalculate severity."""
    if not isinstance(report, Mapping):
        raise ValueError("gate report must be a mapping")
    passed = report.get("passed")
    if type(passed) is not bool:
        raise ValueError("gate report field 'passed' must be a boolean")

    severity = _required_string(report, "regression_level")
    if severity not in {"none", "low", "medium", "high"}:
        raise ValueError("gate report contains an unknown regression severity")
    max_level = _required_string(report, "max_regression_level")
    if max_level not in {"none", "low", "medium", "high"}:
        raise ValueError("gate report contains an unknown maximum regression severity")

    if "steps_by_change" not in report:
        raise ValueError("gate report is missing required field 'steps_by_change'")
    changes = report["steps_by_change"]
    if not isinstance(changes, Mapping):
        raise ValueError("gate report field 'steps_by_change' must be a mapping")
    if any(not isinstance(key, str) for key in changes):
        raise ValueError("gate report change-kind names must be strings")

    unknown_kinds = sorted(key for key in changes if key not in _CHANGE_DEFINITIONS)
    kinds = [kind for kind in _CHANGE_ORDER if kind in changes]
    kinds.extend(unknown_kinds)

    findings: list[dict[str, Any]] = []
    for kind in kinds:
        values = changes[kind]
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError(f"change kind {kind!r} must contain a list of string step identifiers")
        if kind in _CHANGE_DEFINITIONS:
            reason_code, disposition, message = _CHANGE_DEFINITIONS[kind]
        else:
            reason_code, disposition, message = (
                "UNCLASSIFIED_CHANGE",
                "unclassified",
                "Unrecognized engine change kind; human review is required.",
            )
        occurrences: Counter[str] = Counter()
        for step in sorted(values):
            occurrences[step] += 1
            identity = json.dumps(
                [reason_code, kind, step, occurrences[step]],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
            findings.append(
                {
                    "finding_id": hashlib.sha256(identity).hexdigest(),
                    "reason_code": reason_code,
                    "disposition": disposition,
                    "source_change_kind": kind,
                    "step_identifier": step,
                    "message": message,
                }
            )

    by_reason = Counter(item["reason_code"] for item in findings)
    divergence_count = sum(
        item["disposition"] in {"divergence", "unclassified"} for item in findings
    )
    informational_count = sum(
        item["disposition"] == "accepted_equivalence" for item in findings
    )
    fingerprint_match = report.get("fingerprint_match")
    if type(fingerprint_match) is not bool:
        raise ValueError("gate report field 'fingerprint_match' must be a boolean")

    return {
        "schema_version": _SCHEMA_VERSION,
        "source": "dprovenancekit.cli.gate",
        "verdict": "pass" if passed else "fail",
        "severity": severity,
        "policy": {
            "max_regression_level": max_level,
            "allow_divergent_steps": bool(report.get("allow_divergent_steps", False)),
        },
        "fingerprints": {
            "match": fingerprint_match,
            "golden": report.get("golden_fingerprint"),
            "candidate": report.get("candidate_fingerprint"),
        },
        "counts": {
            "total": len(findings),
            "divergence": divergence_count,
            "informational": informational_count,
            "by_reason_code": dict(sorted(by_reason.items())),
        },
        "review_required": any(item["disposition"] == "unclassified" for item in findings),
        "engine_reasoning": str(report.get("reasoning") or ""),
        "findings": findings,
    }


def render_summary(intelligence: Mapping[str, Any]) -> str:
    """Render a Markdown summary with inert trace-derived table cells."""
    counts = intelligence.get("counts") or {}
    findings = intelligence.get("findings") or []
    lines = [
        "### Regression Intelligence v1",
        "",
        f"- **Divergences:** {counts.get('divergence', 0)}",
        f"- **Accepted equivalences:** {counts.get('informational', 0)}",
        f"- **Review required:** {'yes' if intelligence.get('review_required') else 'no'}",
    ]
    if findings:
        lines.extend(["", "| reason code | step | disposition |", "| --- | --- | --- |"])
        for item in findings:
            lines.append(
                f"| `{_safe_cell(item.get('reason_code', ''))}` | "
                f"{_safe_cell(item.get('step_identifier', ''))} | "
                f"{_safe_cell(item.get('disposition', ''))} |"
            )
    else:
        lines.extend(["", "No per-step findings."])
    return "\n".join(lines) + "\n"
