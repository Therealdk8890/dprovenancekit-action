"""Shared sticky pull-request comment upsert for the DProvenanceKit Action.

Standard library only. Used by ``pr_comment.py`` and ``receipt_pr_comment.py``.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

ApiFn = Callable[..., tuple[int, Any]]

_ACTIONS_BOT_LOGIN = "github-actions[bot]"
_PERMISSION_CODES = (401, 403, 404)


def github_api(method: str, url: str, token: str, payload: Any = None, *, user_agent: str) -> tuple[int, Any]:
    """Call the GitHub REST API with a bounded timeout and return ``(status, json)``."""
    if not url.startswith("https://"):
        raise ValueError("GitHub API URL must use https")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        body = resp.read()
        return resp.status, (json.loads(body) if body else None)


_MAX_EDIT_ATTEMPTS = 5


def sticky_comment_candidates(comments: Any, marker: str) -> list[Mapping[str, Any]]:
    """Marker comments in edit-preference order: Actions-bot comments first.

    Any participant can post a comment containing the hidden marker, so the
    GitHub Actions bot's comments are tried first, then the rest (for example
    comments written earlier with a PAT ``github-token``).
    """
    candidates = [
        c for c in (comments or [])
        if isinstance(c, Mapping) and marker in (c.get("body") or "") and "id" in c
    ]

    def is_actions_bot(comment: Mapping[str, Any]) -> bool:
        user = comment.get("user") or {}
        return user.get("login") == _ACTIONS_BOT_LOGIN and user.get("type") == "Bot"

    return sorted(candidates, key=lambda c: not is_actions_bot(c))


def find_sticky_comment(comments: Any, marker: str) -> Mapping[str, Any] | None:
    """Return the preferred marker comment, or ``None``."""
    candidates = sticky_comment_candidates(comments, marker)
    return candidates[0] if candidates else None


def pull_request_number(event_path: str) -> int | None:
    with open(event_path, encoding="utf-8") as fh:
        event = json.load(fh)
    pr = (event.get("pull_request") or {}).get("number") or event.get("number")
    return pr if isinstance(pr, int) and pr > 0 else None


def upsert_sticky_comment(body: str, marker: str, env: Mapping[str, str], api: ApiFn) -> int | None:
    """Create or update the marker comment on the current pull request.

    Returns the PR number on success, or ``None`` when posting was skipped (no
    token, not a pull_request event, or insufficient permissions).
    """
    token = env.get("GITHUB_TOKEN")
    event_path = env.get("GITHUB_EVENT_PATH")
    repo = env.get("GITHUB_REPOSITORY")
    api_url = (env.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")

    if not token or not event_path or not repo:
        print("dprovenancekit: no token / event context; comment body follows:\n" + body)
        return None

    pr = pull_request_number(event_path)
    if pr is None:
        print("dprovenancekit: not a pull_request event; skipping comment")
        return None

    comments_url = f"{api_url}/repos/{repo}/issues/{pr}/comments?per_page=100"
    post_url = f"{api_url}/repos/{repo}/issues/{pr}/comments"
    try:
        _, comments = api("GET", comments_url, token)
        candidates = sticky_comment_candidates(comments, marker)[:_MAX_EDIT_ATTEMPTS]
        for existing in candidates:
            try:
                api(
                    "PATCH",
                    f"{api_url}/repos/{repo}/issues/comments/{existing['id']}",
                    token,
                    {"body": body},
                )
                return pr
            except urllib.error.HTTPError as exc:
                if exc.code not in _PERMISSION_CODES:
                    raise
                # Not editable with this token (another author); try the next one.
        api("POST", post_url, token, {"body": body})
    except urllib.error.HTTPError as exc:
        if exc.code in _PERMISSION_CODES:
            print(
                "dprovenancekit: insufficient permissions to comment "
                "(fork PR token is read-only?); skipping",
                file=sys.stderr,
            )
            return None
        raise
    return pr
