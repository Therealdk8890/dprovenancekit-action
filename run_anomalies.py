#!/usr/bin/env python3
"""Run DProvenanceKit anomaly rules over the candidate run and publish Action outputs.

Invoked by ``action.yml`` when ``anomaly-rules`` is set. Runs
``python -m dprovenancekit.cli anomalies --json`` scoped to the candidate run, writes
``anomaly-count`` / ``anomalies-json`` to ``$GITHUB_OUTPUT``, appends a table to
``$GITHUB_STEP_SUMMARY``, and prints one ``::warning::`` annotation per anomaly.

It does NOT fail the job — a later ``action.yml`` step enforces that from ``anomaly-count``
when ``fail-on-anomaly`` is true. Returns non-zero only on a real error (bad config / run not
found), mirroring the CLI's exit code 2. Standard library only.
"""

from __future__ import annotations

import html
import json
import os
import secrets
import subprocess
import sys


def resolve_candidate(env, run=subprocess.run):
    """The candidate run id: explicit, or the newest run for DPROV_CANDIDATE_CONTEXT.

    Returns ``(run_id_or_none, error_or_none)`` — ``(None, None)`` means no candidate
    scoping at all (rules scan every run), which stays valid behavior.
    """
    if env.get("DPROV_CANDIDATE"):
        return env["DPROV_CANDIDATE"], None
    context = env.get("DPROV_CANDIDATE_CONTEXT")
    if not context:
        return None, None
    proc = run(
        [
            sys.executable, "-m", "dprovenancekit.cli", "runs",
            "--db", env["DPROV_DB"],
            "--context", context,
            "--latest", "--format", "id",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, proc.stderr.strip() or f"no run found for context '{context}'"
    return proc.stdout.strip().splitlines()[0], None


def build_argv(env, candidate=None):
    """Build the ``python -m dprovenancekit.cli anomalies`` command from the environment."""
    if candidate is None:
        candidate = env.get("DPROV_CANDIDATE")
    argv = [
        sys.executable, "-m", "dprovenancekit.cli", "anomalies",
        "--db", env["DPROV_DB"],
        "--rules", env["DPROV_ANOMALY_RULES"],
        "--json",
    ]
    if candidate:
        argv += ["--run", candidate]
    return argv


def write_outputs(pairs, path):
    """Append ``pairs`` to ``$GITHUB_OUTPUT`` with a random, collision-free delimiter."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in pairs:
            value = str(value)
            lines = value.splitlines()
            delimiter = f"__DPROV_{secrets.token_hex(16)}__"
            while delimiter in lines:
                delimiter = f"__DPROV_{secrets.token_hex(16)}__"
            fh.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def _one_line(value):
    """Collapse newlines/carriage returns so trace-derived text can't inject a workflow
    command (``::error::``) into the job log or break out of a markdown table cell."""
    return str(value).replace("\r", " ").replace("\n", " ")


def _cell(value):
    """One-line, inert text for a Markdown table cell (no HTML, pipes, or code spans)."""
    return html.escape(_one_line(value), quote=True).replace("|", "&#124;").replace("`", "&#96;")


def _escape_data(value):
    """Escape a workflow-command message (GitHub ``escapeData`` rules)."""
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value):
    """Escape a workflow-command property value (GitHub ``escapeProperty`` rules)."""
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def render_annotations(report):
    """One GitHub ``::warning::`` annotation line per anomaly.

    Rule names and descriptions come from trace data, so both are escaped and
    cannot terminate the command early or start a new workflow command.
    """
    lines = []
    for anomaly in report.get("anomalies", []):
        title = _escape_property(f"DProvenanceKit anomaly ({anomaly.get('rule')})")
        lines.append(f"::warning title={title}::{_escape_data(anomaly.get('description'))}")
    return lines


def render_summary(report):
    """A markdown section for ``$GITHUB_STEP_SUMMARY``."""
    count = report.get("count", 0)
    if not count:
        return "### DProvenanceKit anomaly rules\n\nNo anomalies detected.\n"
    rows = "\n".join(
        f"| {_cell(a.get('rule'))} | {_cell(a.get('description'))} |"
        for a in report.get("anomalies", [])
    )
    return (
        "### DProvenanceKit anomaly rules\n\n"
        f"{count} anomaly(ies) detected.\n\n"
        "| rule | detail |\n| --- | --- |\n" + rows + "\n"
    )


def validate_report(report, returncode):
    """Return an error message when the anomalies report cannot be trusted."""
    if not isinstance(report, dict):
        return "anomalies report must be a JSON object"
    count = report.get("count", 0)
    if type(count) is not int or count < 0:
        return "anomalies report field 'count' must be a non-negative integer"
    anomalies = report.get("anomalies", [])
    if not isinstance(anomalies, list) or not all(isinstance(a, dict) for a in anomalies):
        return "anomalies report field 'anomalies' must be a list of objects"
    if returncode == 1 and count == 0:
        return "anomalies command exited 1 (anomalies found) but reported count=0"
    return None


def main(env=None):
    env = dict(os.environ if env is None else env)
    try:
        candidate, resolve_error = resolve_candidate(env)
        if resolve_error is not None:
            print(
                f"error: could not resolve candidate run: {resolve_error}",
                file=sys.stderr,
            )
            return 2
        argv = build_argv(env, candidate)
    except KeyError as exc:
        print(f"error: missing required input {exc}", file=sys.stderr)
        return 2

    proc = subprocess.run(argv, capture_output=True, text=True)
    # anomalies exit codes: 0 none, 1 found, 2 usage / config / not-found. Any other
    # status is treated as an error so enforcement fails closed.
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        if proc.returncode != 2:
            print(
                f"error: anomalies command exited with unexpected status {proc.returncode}",
                file=sys.stderr,
            )
        return 2
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stderr or proc.stdout)
        print("error: anomalies command did not emit a JSON report", file=sys.stderr)
        return 2
    error = validate_report(report, proc.returncode)
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        return 2

    write_outputs(
        [
            ("anomaly-count", str(report.get("count", 0))),
            ("anomalies-json", json.dumps(report)),
        ],
        env.get("GITHUB_OUTPUT"),
    )

    for line in render_annotations(report):
        print(line)
    step_summary = env.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(render_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

