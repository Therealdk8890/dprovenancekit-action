#!/usr/bin/env python3
"""Post (or update) a sticky PR comment for the Verification Receipt gate.

Reuses the same upsert pattern as ``pr_comment.py`` with a distinct marker so
path-gate and receipt-gate comments do not overwrite each other.
Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

_MARKER = "<!-- dprovenancekit-verification-receipt-gate -->"


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
        f"- **Status:** `{status}`",
        f"- **Invariant:** `{report.get('invariant_id', '')}`",
        f"- **Integrity:** {'pass' if report.get('integrity_ok') else 'fail'}",
        f"- **Invariant eval:** {'pass' if report.get('invariant_ok') else 'fail'}",
    ]
    reason = report.get("reason")
    if reason:
        lines += ["", f"_{reason}_"]
    lines += [
        "",
        "> Verified means integrity-protected provenance satisfied the declared "
        "invariant — not that the claim is objectively true.",
    ]
    return "\n".join(lines)


def _api(method, url, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "dprovenancekit-verification-receipt-gate",
        },
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return resp.status, (json.loads(body) if body else None)


def post_comment(report, env, api=_api):
    body = render_receipt_comment(report)
    token = env.get("GITHUB_TOKEN")
    event_path = env.get("GITHUB_EVENT_PATH")
    repo = env.get("GITHUB_REPOSITORY")
    api_url = env.get("GITHUB_API_URL", "https://api.github.com")

    if not token or not event_path or not repo:
        print("dprovenancekit: no token / event context; comment body follows:\n" + body)
        return None

    with open(event_path, encoding="utf-8") as fh:
        event = json.load(fh)
    pr = (event.get("pull_request") or {}).get("number") or event.get("number")
    if not pr:
        print("dprovenancekit: not a pull_request event; skipping comment")
        return None

    comments_url = f"{api_url}/repos/{repo}/issues/{pr}/comments?per_page=100"
    post_url = f"{api_url}/repos/{repo}/issues/{pr}/comments"
    try:
        _, comments = api("GET", comments_url, token)
        existing = next(
            (c for c in (comments or []) if _MARKER in (c.get("body") or "")), None
        )
        if existing:
            api(
                "PATCH",
                f"{api_url}/repos/{repo}/issues/comments/{existing['id']}",
                token,
                {"body": body},
            )
        else:
            api("POST", post_url, token, {"body": body})
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            print(
                "dprovenancekit: insufficient permissions to comment "
                "(fork PR token is read-only?); skipping",
                file=sys.stderr,
            )
            return None
        raise
    return pr


def main(env=None):
    env = dict(os.environ if env is None else env)
    raw = env.get("DPROV_REPORT_JSON")
    if not raw:
        print("error: DPROV_REPORT_JSON is empty", file=sys.stderr)
        return 1
    post_comment(json.loads(raw), env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
