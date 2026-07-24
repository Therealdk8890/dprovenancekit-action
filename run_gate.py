#!/usr/bin/env python3
"""Run the DProvenanceKit regression gate and publish GitHub Action step outputs.

Invoked by ``action.yml`` (composite). Runs ``python -m dprovenancekit.cli gate --json``
against a local SQLite database, then writes step outputs (``passed``, ``regression-level``,
``summary``, ``report-json``) to ``$GITHUB_OUTPUT`` and a short report to
``$GITHUB_STEP_SUMMARY``.

It deliberately does NOT fail the job when a regression is found — a later ``action.yml``
step enforces that from the ``passed`` output — so the PR-comment step still runs on a
failing gate. It returns non-zero only on a real error (bad input / run not found), mirroring
the gate's own exit code 2.

Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import hashlib
from dataclasses import dataclass

@dataclass
class IngestResult:
    uploaded: bool
    server_run_id: str | None
    viewer_url: str | None

def normalize_export_event(row: dict) -> dict:
    if "event_id" not in row:
        raise ValueError(f"Export row is missing required field 'event_id': {row}")
    if "run_id" not in row:
        raise ValueError(f"Export row is missing required field 'run_id': {row}")
    if "context_id" not in row:
        raise ValueError(f"Export row is missing required field 'context_id': {row}")
    if "priority" not in row:
        raise ValueError(f"Export row is missing required field 'priority': {row}")
    if "sequence" not in row:
        raise ValueError(f"Export row is missing required field 'sequence': {row}")
    if "engine" not in row:
        raise ValueError(f"Export row is missing required field 'engine': {row}")
    if "type" not in row:
        raise ValueError(f"Export row is missing required field 'type': {row}")
    if "timestamp" not in row:
        raise ValueError(f"Export row is missing required field 'timestamp': {row}")
        
    return {
        "id": row["event_id"],
        "run_id": row["run_id"],
        "context_id": row["context_id"],
        "priority": row["priority"],
        "sequence": row["sequence"],
        "engine": row["engine"],
        "span_id": row.get("span_id"),
        "parent_span_id": row.get("parent_span_id"),
        "type": row["type"],
        "payload": row.get("data"),
        "timestamp": row["timestamp"],
    }

import urllib.request
import urllib.error

# An unlikely delimiter for the $GITHUB_OUTPUT multiline (heredoc) format.
_DELIM = "__DPROV_OUTPUT_EOF__"


def resolve_run(env, run_key, context_key, db, run=subprocess.run):
    """The run id for one side: explicit, or the newest run for its context id.

    Resolution shells out to ``dprovenancekit runs --latest --format id`` (available
    since 0.3.x) rather than the gate's own ``--golden-context`` flags, so the action
    works with whatever SDK version ``install-spec`` installed. An explicit run id
    wins — both may legitimately be set (e.g. candidate-run-id to scope anomaly rules
    alongside candidate-context). Returns ``(run_id_or_none, error_or_none)``.
    """
    if env.get(run_key):
        return env[run_key], None
    context = env.get(context_key)
    if not context:
        side = run_key.removeprefix("DPROV_").lower()
        return None, (
            f"no {side} run selected — set the {side}-run-id or "
            f"{side}-context input"
        )
    proc = run(
        [
            sys.executable, "-m", "dprovenancekit.cli", "runs",
            "--db", db,
            "--context", context,
            "--latest", "--format", "id",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, proc.stderr.strip() or f"no run found for context '{context}'"
    return proc.stdout.strip().splitlines()[0], None


def build_gate_argv(env, golden=None, candidate=None):
    """Build the ``python -m dprovenancekit.cli gate`` command from the step environment."""
    golden_db = env.get("DPROV_GOLDEN_DB") or env["DPROV_DB"]
    candidate_db = env.get("DPROV_CANDIDATE_DB") or env["DPROV_DB"]
    argv = [
        sys.executable, "-m", "dprovenancekit.cli", "gate",
        "--golden-db", golden_db,
        "--candidate-db", candidate_db,
        "--golden", golden if golden is not None else env["DPROV_GOLDEN"],
        "--candidate", candidate if candidate is not None else env["DPROV_CANDIDATE"],
        "--max-level", (env.get("DPROV_MAX_LEVEL") or "none"),
        "--json",
    ]
    if str(env.get("DPROV_ALLOW_DIVERGENT", "")).strip().lower() == "true":
        argv.append("--allow-divergent")
    return argv


def render_outputs(report):
    """Map a gate report dict to ordered ``(key, value)`` GitHub output pairs."""
    return [
        ("passed", "true" if report.get("passed") else "false"),
        ("regression-level", str(report.get("regression_level", ""))),
        ("summary", report.get("summary", "")),
        ("report-json", json.dumps(report)),
    ]


def write_outputs(pairs, path):
    """Append ``pairs`` to ``$GITHUB_OUTPUT`` using the multiline heredoc format."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in pairs:
            fh.write(f"{key}<<{_DELIM}\n{value}\n{_DELIM}\n")


def ingest_run(env, db_path, run_id, report) -> IngestResult:
    cloud_mode = env.get("DPROV_CLOUD_MODE", "off").lower()
    if cloud_mode not in {"off", "optional", "required"}:
        print(f"error: invalid cloud-mode '{cloud_mode}'. Must be 'off', 'optional', or 'required'.", file=sys.stderr)
        raise SystemExit(2)
        
    if cloud_mode == "off":
        return IngestResult(False, None, None)

    cloud_url = env.get("DPROV_CLOUD_URL", "https://api.dprovenance.dev").rstrip("/")
    api_key = env.get("DPROV_CLOUD_API_KEY", "")
    project_id = env.get("DPROV_PROJECT_ID", "")
    
    if not api_key:
        print("warning: DPROV_CLOUD_API_KEY not set. Skipping ingestion.", file=sys.stderr)
        if cloud_mode == "required":
            raise SystemExit(1)
        return False, None
        
    if not project_id:
        print("warning: DPROV_PROJECT_ID not set. Skipping ingestion.", file=sys.stderr)
        if cloud_mode == "required":
            raise SystemExit(1)
        return False, None
        
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "dprovenancekit.cli", "export", "--db", db_path, "--run", run_id, "--format", "jsonl"],
            capture_output=True, text=True, check=True
        )
        
        events = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                events.append(normalize_export_event(row))
            except Exception as e:
                print(f"error processing export row: {e}", file=sys.stderr)
                if cloud_mode == "required":
                    raise SystemExit(1)
                return IngestResult(False, None, None)
            
        if not events:
            print(f"warning: run {run_id} produced no events during export", file=sys.stderr)
            if cloud_mode == "required":
                raise SystemExit(1)
            return IngestResult(False, None, None)
            
        context_id = events[0].get("context_id", "unknown")
            
        gate_report_sha256 = hashlib.sha256(json.dumps(report).encode("utf-8")).hexdigest()

        run_metadata = {
            "client_run_id": run_id,
            "context_id": context_id,
            "commit_sha": os.environ.get("GITHUB_SHA"),
            "branch": os.environ.get("GITHUB_REF_NAME"),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_event": os.environ.get("GITHUB_EVENT_NAME"),
            "gate_status": "passed" if report.get("passed") else "failed",
            "gate_report_sha256": gate_report_sha256,
        }
        
        artifacts_json = env.get("DPROV_ARTIFACTS", "[]")
        try:
            artifacts = json.loads(artifacts_json)
        except Exception:
            artifacts = []
            
        payload = {
            "schema_version": "dprov.ingest.v1",
            "project_id": project_id,
            "run": run_metadata,
            "events": events,
            "artifacts": artifacts
        }
        
        req = urllib.request.Request(
            f"{cloud_url}/api/v1/traces/ingest",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = json.loads(resp.read())
            
            if "run_id" not in resp_body or "viewer_url" not in resp_body or "content_sha256" not in resp_body:
                print("error: malformed backend response, missing required fields.", file=sys.stderr)
                if cloud_mode == "required":
                    raise SystemExit(1)
                return IngestResult(False, None, None)
                
            print("Successfully ingested run to cloud.", file=sys.stderr)
            return IngestResult(True, resp_body.get("run_id"), resp_body.get("viewer_url"))
    except Exception as exc:
        print(f"error during ingestion: {exc}", file=sys.stderr)
        if cloud_mode == "required":
            raise SystemExit(1)
        return IngestResult(False, None, None)


def promote_baseline(env, run_id):
    if not env.get("DPROV_CLOUD_MODE") or env["DPROV_CLOUD_MODE"] == "off":
        return True
    if env.get("DPROV_PROMOTE_BASELINE", "false").lower() != "true":
        return True
        
    cloud_url = env.get("DPROV_CLOUD_URL", "https://api.dprovenance.dev").rstrip("/")
    api_key = env.get("DPROV_CLOUD_API_KEY", "")
    project_id = env.get("DPROV_PROJECT_ID", "")
    
    if not api_key or not project_id:
        return False
        
    try:
        payload = {
            "project_id": project_id,
            "run_id": run_id
        }
        req = urllib.request.Request(
            f"{cloud_url}/api/v1/baselines/promote",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
            print("Successfully promoted run to baseline.", file=sys.stderr)
            return True
    except Exception as exc:
        print(f"warning: failed to promote baseline: {exc}", file=sys.stderr)
        return False


def main(env=None):
    env = dict(os.environ if env is None else env)
    try:
        golden_db = env.get("DPROV_GOLDEN_DB") or env["DPROV_DB"]
        candidate_db = env.get("DPROV_CANDIDATE_DB") or env["DPROV_DB"]
        golden, golden_error = resolve_run(
            env, "DPROV_GOLDEN", "DPROV_GOLDEN_CONTEXT", golden_db
        )
        candidate, candidate_error = resolve_run(
            env, "DPROV_CANDIDATE", "DPROV_CANDIDATE_CONTEXT", candidate_db
        )
        for error in (golden_error, candidate_error):
            if error is not None:
                print(f"error: {error}", file=sys.stderr)
        if golden is None or candidate is None:
            return 2
        argv = build_gate_argv(env, golden, candidate)
    except KeyError as exc:
        print(f"error: missing required input {exc}", file=sys.stderr)
        return 2

    proc = subprocess.run(argv, capture_output=True, text=True)
    # Gate exit codes: 0 pass, 1 regression, 2 usage / run-not-found.
    if proc.returncode == 2:
        sys.stderr.write(proc.stderr)
        return 2
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stderr or proc.stdout)
        print("error: gate did not emit a JSON report", file=sys.stderr)
        return 2

    # Ingest candidate run to cloud if configured
    ingest_result = ingest_run(env, candidate_db, candidate, report)
    if ingest_result.viewer_url:
        report["viewer_url"] = ingest_result.viewer_url

    write_outputs(render_outputs(report), env.get("GITHUB_OUTPUT"))

    summary = report.get("summary", "")
    print(summary)
    step_summary = env.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("### DProvenanceKit regression gate\n\n```\n" + summary + "\n```\n")
            if ingest_result.viewer_url:
                fh.write(f"\n[🔍 View full regression trace in DProvenance Cloud]({ingest_result.viewer_url})\n")
    
    # Promote to baseline if gate passed and promotion is requested
    promote_requested = env.get("DPROV_PROMOTE_BASELINE", "false").lower() == "true"
    cloud_mode = env.get("DPROV_CLOUD_MODE", "off").lower()
    
    if report.get("passed") and promote_requested and ingest_result.server_run_id:
        github_event = env.get("GITHUB_EVENT_NAME", "")
        github_ref = env.get("GITHUB_REF_NAME", "")
        configured_branch = env.get("DPROV_DEFAULT_BRANCH", "main")
        
        can_promote = True
        if github_event != "push":
            print("warning: baseline promotion requires a push workflow", file=sys.stderr)
            can_promote = False
        if github_ref != configured_branch:
            print("warning: baseline promotion requires the default branch", file=sys.stderr)
            can_promote = False
            
        if can_promote:
            promotion_ok = promote_baseline(env, ingest_result.server_run_id)
            if not promotion_ok and cloud_mode == "required":
                print("error: required baseline promotion failed", file=sys.stderr)
                return 1
                
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
