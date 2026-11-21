#!/usr/bin/env python3
"""Post (or update) a sticky pull-request comment summarizing the regression gate.

Reads the gate report JSON from ``$DPROV_REPORT_JSON``, renders markdown, and upserts a
single comment on the PR (found via a hidden marker) using ``$GITHUB_TOKEN``. Re-runs edit
the same comment in place instead of stacking new ones.

On a fork PR the ``GITHUB_TOKEN`` is read-only, so posting is skipped with a notice rather
than failing the job. Standard library only (``urllib``).
"""

from __future__ import annotations

import html
import json
import os
import re
import sys

from github_comment import github_api, upsert_sticky_comment

_MARKER = "<!-- dprovenancekit-regression-gate -->"
_CHANGE_ORDER = ("removed", "added", "reordered", "ambiguous")
_MARKDOWN_META = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


def _cell(value):
    """Render trace-derived values as inert Markdown table-cell content."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return html.escape(text, quote=True).replace("|", "&#124;").replace("`", "&#96;")


def _safe_inline(value):
    """Escape trace-derived prose so it cannot add Markdown structure or HTML."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return _MARKDOWN_META.sub(r"\\\1", html.escape(text, quote=True))


def render_comment(report):
    """Render the gate report dict as a sticky PR-comment markdown body (pure function)."""
    passed = bool(report.get("passed"))
    badge = "✅ **Regression gate passed**" if passed else "❌ **Regression gate failed**"
    level = report.get("regression_level", "none")
    strength = float(report.get("strength", 0.0) or 0.0)
    fp_match = report.get("fingerprint_match")

    lines = [
        _MARKER,
        "## DProvenanceKit",
        "",
        badge,
        "",
        f"- **Severity:** {_cell(level)} (strength {strength:.2f}); "
        f"max allowed: {_cell(report.get('max_regression_level', 'none'))}",
        f"- **Fingerprint:** {'match' if fp_match else 'differs'}",
    ]

    intelligence = report.get("regression_intelligence")
    if intelligence:
        counts = intelligence.get("counts") or {}
        lines += [
            "",
            "### Regression Intelligence v1",
            "",
            f"- **Divergences:** {counts.get('divergence', 0)}",
            f"- **Accepted equivalences:** {counts.get('informational', 0)}",
            f"- **Review required:** {'yes' if intelligence.get('review_required') else 'no'}",
        ]
        findings = intelligence.get("findings") or []
        if findings:
            lines += ["", "| reason code | step | disposition |", "| --- | --- | --- |"]
            lines += [
                f"| `{_cell(item.get('reason_code', ''))}` | "
                f"{_cell(item.get('step_identifier', ''))} | "
                f"{_cell(item.get('disposition', ''))} |"
                for item in findings
            ]
        else:
            lines.append("- No per-step findings.")
    else:
        changes = report.get("steps_by_change") or {}
        rows = [(kind, changes[kind]) for kind in _CHANGE_ORDER if changes.get(kind)]
        if rows:
            lines += ["", "| change | steps |", "| --- | --- |"]
            lines += [
                f"| {kind} | {', '.join(_cell(step) for step in steps)} |"
                for kind, steps in rows
            ]
        else:
            lines.append("- No per-step changes (all exact matches).")

    reasoning = report.get("reasoning")
    if reasoning:
        lines += ["", _safe_inline(reasoning)]

    viewer_url = report.get("viewer_url")
    if viewer_url:
        # Treat the URL as plain escaped text rather than interpolating it into Markdown.
        lines += ["", f"Viewer URL: {_cell(viewer_url)}"]

    return "\n".join(lines)


def _api(method, url, token, payload=None):
    return github_api(method, url, token, payload, user_agent="dprovenancekit-regression-gate")


def post_comment(report, env, api=_api):
    """Upsert the sticky comment on the PR named by the GitHub event payload.

    Returns the PR number on success, or ``None`` when posting was skipped (no token, not a
    pull_request event, or insufficient permissions).
    """
    return upsert_sticky_comment(render_comment(report), _MARKER, env, api)


def main(env=None):
    env = dict(os.environ if env is None else env)
    raw = env.get("DPROV_REPORT_JSON")
    if not raw:
        print("error: DPROV_REPORT_JSON is empty", file=sys.stderr)
        return 1
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: DPROV_REPORT_JSON is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(report, dict):
        print("error: DPROV_REPORT_JSON must be a JSON object", file=sys.stderr)
        return 1
    post_comment(report, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
