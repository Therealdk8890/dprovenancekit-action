#!/usr/bin/env python3
"""Unit tests for the Verification Receipt gate evaluator (stdlib unittest)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import receipt_gate  # noqa: E402
import receipt_pr_comment  # noqa: E402

FIXTURES = ROOT / "fixtures" / "verification-receipt"
INVARIANT = FIXTURES / "invariant-claim-path-v1.json"


class TestEvaluateFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.invariant = receipt_gate.load_json(INVARIANT)

    def _eval(self, name: str):
        receipt = receipt_gate.load_json(FIXTURES / name)
        return receipt, receipt_gate.evaluate_receipt(receipt, self.invariant)

    def test_verified_fixture(self):
        receipt, result = self._eval("verified.json")
        self.assertEqual(result.status, "verified")
        self.assertTrue(result.integrity_ok)
        self.assertTrue(result.invariant_ok)
        self.assertTrue(result.status_consistent)
        self.assertEqual(result.receipt_status_field, receipt["status"])
        self.assertEqual(result.invariant_id, "claim-path-v1")
        self.assertTrue(receipt_gate.gate_should_pass(result.status, {"incomplete", "tampered"}))

    def test_incomplete_fixture(self):
        receipt, result = self._eval("incomplete.json")
        self.assertEqual(result.status, "incomplete")
        self.assertTrue(result.integrity_ok)
        self.assertFalse(result.invariant_ok)
        self.assertTrue(result.status_consistent)
        self.assertIn("verify", result.reason)
        self.assertFalse(receipt_gate.gate_should_pass(result.status, {"incomplete", "tampered"}))

    def test_tampered_fixture(self):
        receipt, result = self._eval("tampered.json")
        self.assertEqual(result.status, "tampered")
        self.assertFalse(result.integrity_ok)
        self.assertTrue(result.invariant_ok)  # steps still satisfy claim-path-v1
        self.assertTrue(result.status_consistent)
        self.assertFalse(receipt_gate.gate_should_pass(result.status, {"incomplete", "tampered"}))

    def test_does_not_trust_declared_status_blindly(self):
        receipt = receipt_gate.load_json(FIXTURES / "verified.json")
        # Corrupt integrity while leaving status=verified on the document.
        receipt = dict(receipt)
        receipt["integrity"] = {
            "evidence": True,
            "trace": False,
            "files_unchanged": True,
        }
        result = receipt_gate.evaluate_receipt(receipt, self.invariant)
        self.assertEqual(result.status, "tampered")
        self.assertFalse(result.status_consistent)
        self.assertEqual(result.receipt_status_field, "verified")

    def test_ordering_violation_incomplete(self):
        receipt = receipt_gate.load_json(FIXTURES / "verified.json")
        receipt = dict(receipt)
        receipt["steps"] = [
            {"type": "evidence", "label": "Evidence"},
            {"type": "verify", "label": "Verify"},
            {"type": "extract", "label": "Extract"},
            {"type": "claim", "label": "Claim"},
        ]
        result = receipt_gate.evaluate_receipt(receipt, self.invariant)
        self.assertEqual(result.status, "incomplete")
        self.assertIn("ordering", result.reason.lower())

    def test_must_include_verify(self):
        ok, reason = receipt_gate.evaluate_invariant(
            [
                {"type": "evidence", "label": "E"},
                {"type": "extract", "label": "X"},
                {"type": "claim", "label": "C"},
            ],
            self.invariant,
        )
        self.assertFalse(ok)
        self.assertIn("verify", reason or "")


class TestMainCli(unittest.TestCase):
    def test_main_verified_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "github_output"
            env = {
                "DPROV_RECEIPT_PATH": str(FIXTURES / "verified.json"),
                "DPROV_INVARIANT_PATH": str(INVARIANT),
                "DPROV_FAIL_ON_RECEIPT_STATUSES": "incomplete,tampered",
                "GITHUB_OUTPUT": str(out),
            }
            code = receipt_gate.main(env)
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("receipt-status<<", text)
            self.assertIn("verified", text)
            self.assertIn("passed<<", text)

    def test_main_incomplete_still_exit_zero(self):
        # Enforcement is deferred to action.yml (comment-then-fail pattern).
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "github_output"
            env = {
                "DPROV_RECEIPT_PATH": str(FIXTURES / "incomplete.json"),
                "DPROV_INVARIANT_PATH": str(INVARIANT),
                "GITHUB_OUTPUT": str(out),
            }
            code = receipt_gate.main(env)
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("incomplete", text)
            self.assertIn("passed<<", text)
            # Extract passed value roughly
            self.assertRegex(text, r"passed<<\w+\nfalse\n")


class TestReceiptPrComment(unittest.TestCase):
    def test_render_contains_marker_and_status(self):
        body = receipt_pr_comment.render_receipt_comment(
            {
                "passed": False,
                "status": "incomplete",
                "invariant_id": "claim-path-v1",
                "integrity_ok": True,
                "invariant_ok": False,
                "reason": "Required step type verify is missing.",
            }
        )
        self.assertIn("<!-- dprovenancekit-verification-receipt-gate -->", body)
        self.assertIn("`incomplete`", body)
        self.assertIn("claim-path-v1", body)
        self.assertIn("objectively true", body)


if __name__ == "__main__":
    unittest.main()
