#!/usr/bin/env python3
"""Post (or update) a sticky PR comment for the Verification Receipt gate.

Reuses the same upsert pattern as ``pr_comment.py`` with a distinct marker so
path-gate and receipt-gate comments do not overwrite each other.
Standard library only.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys

from github_comment import github_api, upsert_sticky_comment

_MARKER = "<!-- dprovenancekit-verification-receipt-gate -->"
_MARKDOWN_META = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


def _safe(value) -> str:
    """Escape receipt-derived text so it cannot add Markdown structure or HTML."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return _MARKDOWN_META.sub(r"\\\1", html.escape(text, quote=True))


def _code(value) -> str:
    """Render receipt-derived text as a single inert Markdown code span."""
    text = str(value).replace("\r", " ").replace("\n", " ").replace("`", "'")
    return f"`{text}`"


def render_receipt_comment(report: dict) -> str:
    """Render receipt gate report as sticky PR-comment markdown."""
    passed = bool(report.get("passed"))
    status = report.get("status", "unknown")
    badge = (
        "✅ **Verification Receipt gate passed**"
        if passed
        else "❌ **Verification Receipt gate failed**"
    )
    lines = [
        _MARKER,
        "## DProvenanceKit — Verification Receipt",
        "",
        badge,
        "",
        f"- **Status:** {_code(status)}",
        f"- **Invariant:** {_code(report.get('invariant_id', ''))}",
        f"- **Integrity:** {'pass' if report.get('integrity_ok') else 'fail'}",
        f"- **Invariant eval:** {'pass' if report.get('invariant_ok') else 'fail'}",
    ]
    reason = report.get("reason")
    if reason:
        lines += ["", _safe(reason)]
    lines += [
        "",
        "> Verified means integrity-protected provenance satisfied the declared "
        "invariant — not that the claim is objectively true.",
    ]
    return "\n".join(lines)


def _api(method, url, token, payload=None):
    return github_api(method, url, token, payload, user_agent="dprovenancekit-verification-receipt-gate")


def post_comment(report, env, api=_api):
    """Upsert the sticky comment on the PR named by the GitHub event payload.

    Returns the PR number on success, or ``None`` when posting was skipped (no token, not a
    pull_request event, or insufficient permissions).
    """
    return upsert_sticky_comment(render_receipt_comment(report), _MARKER, env, api)


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
