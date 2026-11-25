#!/usr/bin/env python3
"""Regression tests for fail-closed behavior and untrusted-input handling."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import github_comment  # noqa: E402
import receipt_gate  # noqa: E402
import receipt_pr_comment  # noqa: E402
import run_anomalies  # noqa: E402
import run_gate  # noqa: E402

FIXTURES = ROOT / "fixtures" / "verification-receipt"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class TestReceiptFailsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.invariant = _load("invariant-claim-path-v1.json")

    def test_non_boolean_integrity_flags_are_not_trusted(self) -> None:
        receipt = _load("verified.json")
        receipt["integrity"] = {"evidence": "false", "trace": 1, "files_unchanged": "true"}
        result = receipt_gate.evaluate_receipt(receipt, self.invariant)
        self.assertEqual(result.status, "tampered")
        self.assertFalse(result.integrity_ok)

    def _run_main(self, receipt, invariant=None) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            env = {"DPROV_RECEIPT_PATH": str(receipt_path), "GITHUB_OUTPUT": str(Path(tmp) / "out")}
            if invariant is not None:
                inv_path = Path(tmp) / "invariant.json"
                inv_path.write_text(json.dumps(invariant), encoding="utf-8")
                env["DPROV_INVARIANT_PATH"] = str(inv_path)
            code = _quiet(receipt_gate.main, env)
            out = Path(env["GITHUB_OUTPUT"])
            return code, out.read_text(encoding="utf-8") if out.exists() else ""

    def test_malformed_integrity_flags_are_rejected_not_reclassified(self) -> None:
        receipt = _load("incomplete.json")
        receipt["integrity"]["evidence"] = "false"
        self.assertIsNotNone(receipt_gate.validate_receipt(receipt))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            env = {
                "DPROV_RECEIPT_PATH": str(path),
                "DPROV_FAIL_ON_RECEIPT_STATUSES": "incomplete",
                "GITHUB_OUTPUT": str(Path(tmp) / "out"),
            }
            self.assertEqual(_quiet(receipt_gate.main, env), 2)

    def test_invariant_without_constraints_is_rejected(self) -> None:
        code, outputs = self._run_main(_load("verified.json"), {"id": "empty"})
        self.assertEqual(code, 2)
        self.assertNotIn("passed", outputs)

    def test_invariant_with_wrong_types_is_rejected(self) -> None:
        bad = {"id": "x", "required_steps": "verify"}
        self.assertIsNotNone(receipt_gate.validate_invariant(bad))
        code, _ = self._run_main(_load("verified.json"), bad)
        self.assertEqual(code, 2)

    def test_malformed_steps_are_rejected(self) -> None:
        receipt = _load("verified.json")
        receipt["steps"] = ["evidence", "extract", "verify", "claim"]
        code, outputs = self._run_main(receipt)
        self.assertEqual(code, 2)
        self.assertNotIn("passed", outputs)

    def test_vendored_invariant_is_valid(self) -> None:
        self.assertIsNone(receipt_gate.validate_invariant(self.invariant))

    def test_step_summary_and_comment_escape_receipt_text(self) -> None:
        receipt = _load("incomplete.json")
        receipt["status_reason"] = "<img src=x onerror=alert(1)> [link](https://evil.test)\n## forged"
        result = receipt_gate.evaluate_receipt(receipt, self.invariant)
        summary = receipt_gate.render_step_summary(result, passed=False)
        self.assertNotIn("<img", summary)
        self.assertNotIn("](https://evil.test)", summary)
        self.assertNotIn("\n## forged", summary)
        body = receipt_pr_comment.render_receipt_comment(
            {"passed": False, "status": result.status, "invariant_id": "a`b\nc", "reason": result.reason}
        )
        self.assertNotIn("<img", body)
        self.assertNotIn("\n## forged", body)
        self.assertIn("`a'b c`", body)


class TestAnomaliesHardening(unittest.TestCase):
    def test_output_delimiter_is_random_and_not_forgeable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            payload = "x\n__DPROV_OUTPUT_EOF__\nanomaly-count<<__DPROV_OUTPUT_EOF__\n0"
            run_anomalies.write_outputs([("anomalies-json", payload)], str(out))
            first = out.read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(first.startswith("anomalies-json<<__DPROV_"))
            self.assertNotEqual(first, "anomalies-json<<__DPROV_OUTPUT_EOF__")

    def test_annotations_cannot_inject_workflow_commands(self) -> None:
        lines = run_anomalies.render_annotations(
            {"anomalies": [{"rule": "r::x,y", "description": "d\n::error::forged %"}]}
        )
        self.assertEqual(len(lines), 1)
        self.assertNotIn("\n", lines[0])
        self.assertIn("r%3A%3Ax%2Cy", lines[0])
        self.assertIn("%0A::error::forged %25", lines[0])

    def test_inconsistent_report_fails_closed(self) -> None:
        self.assertIsNotNone(run_anomalies.validate_report({"count": 0, "anomalies": []}, 1))
        self.assertIsNotNone(run_anomalies.validate_report({"count": "3"}, 0))
        self.assertIsNone(run_anomalies.validate_report({"count": 1, "anomalies": [{}]}, 1))


def _gate_env() -> dict:
    return {
        "DPROV_DB": "traces.sqlite",
        "DPROV_GOLDEN": "golden-run",
        "DPROV_CANDIDATE": "candidate-run",
        "DPROV_CLOUD_MODE": "off",
    }


def _report(passed: bool) -> dict:
    return {
        "passed": passed,
        "regression_level": "none" if passed else "high",
        "max_regression_level": "none",
        "summary": "s",
        "allow_divergent_steps": False,
        "fingerprint_match": passed,
        "golden_fingerprint": "a" * 40,
        "candidate_fingerprint": ("a" if passed else "b") * 40,
        "steps_by_change": {} if passed else {"removed": ["verify"]},
    }


class TestRunGateFailsClosed(unittest.TestCase):
    def _main_with(self, returncode: int, stdout: str) -> int:
        fake = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with mock.patch.object(run_gate.subprocess, "run", return_value=fake):
            return _quiet(run_gate.main, _gate_env())

    def test_unexpected_exit_status_is_an_error(self) -> None:
        self.assertEqual(self._main_with(139, json.dumps(_report(True))), 2)

    def test_regression_exit_with_passing_report_is_an_error(self) -> None:
        self.assertEqual(self._main_with(1, json.dumps(_report(True))), 2)

    def test_non_object_report_is_an_error(self) -> None:
        self.assertEqual(self._main_with(0, "[]"), 2)

    def test_normal_pass_and_fail_still_exit_zero(self) -> None:
        self.assertEqual(self._main_with(0, json.dumps(_report(True))), 0)
        self.assertEqual(self._main_with(1, json.dumps(_report(False))), 0)

    def test_cloud_url_requires_https_except_loopback(self) -> None:
        self.assertEqual(run_gate.validate_cloud_url("https://ingest.example.test/"), "https://ingest.example.test")
        self.assertEqual(run_gate.validate_cloud_url("http://localhost:8080"), "http://localhost:8080")
        for bad in ("http://ingest.example.test", "file:///etc/passwd", "ftp://x", "https://user:pw@h.test", ""):
            with self.assertRaises(ValueError, msg=bad):
                run_gate.validate_cloud_url(bad)

    def test_cloud_requests_do_not_follow_redirects(self) -> None:
        handler = run_gate._RefuseRedirects()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "http://evil.test/"))
        self.assertTrue(
            any(isinstance(h, run_gate._RefuseRedirects) for h in run_gate._CLOUD_OPENER.handlers)
        )

    def test_export_row_errors_do_not_echo_payload(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            run_gate.normalize_export_event({"event_id": "e", "data": "SECRET-PAYLOAD"})
        self.assertNotIn("SECRET-PAYLOAD", str(ctx.exception))


class TestStickyComment(unittest.TestCase):
    MARKER = "<!-- marker -->"

    def test_prefers_comment_authored_by_actions_bot(self) -> None:
        comments = [
            {"id": 1, "body": self.MARKER, "user": {"login": "someone", "type": "User"}},
            {"id": 2, "body": self.MARKER, "user": {"login": "github-actions[bot]", "type": "Bot"}},
        ]
        self.assertEqual(github_comment.find_sticky_comment(comments, self.MARKER)["id"], 2)

    def test_falls_back_to_post_when_marker_comment_is_not_editable(self) -> None:
        calls = []

        def api(method, url, token, payload=None):
            calls.append(method)
            if method == "GET":
                return 200, [{"id": 9, "body": self.MARKER, "user": {"login": "x", "type": "User"}}]
            if method == "PATCH":
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            return 201, {}

        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            event.write_text(json.dumps({"pull_request": {"number": 7}}), encoding="utf-8")
            env = {"GITHUB_TOKEN": "t", "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r"}
            pr = _quiet(github_comment.upsert_sticky_comment, "body", self.MARKER, env, api)
        self.assertEqual(pr, 7)
        self.assertEqual(calls, ["GET", "PATCH", "POST"])

    def test_edits_editable_marker_comment_instead_of_stacking(self) -> None:
        calls = []

        def api(method, url, token, payload=None):
            calls.append((method, url.rsplit("/", 1)[-1]))
            if method == "GET":
                return 200, [
                    {"id": 1, "body": self.MARKER, "user": {"login": "github-actions[bot]", "type": "Bot"}},
                    {"id": 2, "body": self.MARKER, "user": {"login": "pat-user", "type": "User"}},
                ]
            if method == "PATCH" and url.endswith("/1"):
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            return 200, {}

        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            event.write_text(json.dumps({"number": 3}), encoding="utf-8")
            env = {"GITHUB_TOKEN": "t", "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r"}
            _quiet(github_comment.upsert_sticky_comment, "body", self.MARKER, env, api)
        self.assertEqual([c[0] for c in calls], ["GET", "PATCH", "PATCH"])
        self.assertEqual(calls[-1][1], "2")

    def test_github_api_rejects_non_https(self) -> None:
        with self.assertRaises(ValueError):
            github_comment.github_api("GET", "http://api.example.test", "t", user_agent="x")


if __name__ == "__main__":
    unittest.main()


class GateReportUploadTests(unittest.TestCase):
    def test_uploaded_report_is_exactly_the_bytes_behind_its_digest(self) -> None:
        report = {"passed": False, "drift": [{"step": "verify", "kind": "missing"}], "note": "é"}
        serialized, digest = run_gate.gate_report_fields(report)
        self.assertEqual(serialized, json.dumps(report))  # unchanged serialization
        self.assertEqual(digest, hashlib.sha256(serialized.encode("utf-8")).hexdigest())
        self.assertEqual(json.loads(serialized), report)
