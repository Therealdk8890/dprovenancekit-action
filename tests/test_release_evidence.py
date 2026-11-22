"""Positive and negative tests for preliminary unsigned release-evidence manifests."""
import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "release_evidence.py"
SPEC = importlib.util.spec_from_file_location("release_evidence", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "gate.json"
        self.artifact.write_text('{"passed":false}', encoding="utf-8")
        self.manifest = self.root / "manifest.json"
        MODULE.create(Namespace(
            baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
            verdict="block", artifact=[str(self.artifact)], output=str(self.manifest)
        ))

    def test_valid_manifest(self):
        MODULE.verify(self.manifest)

    def test_modified_artifact_fails(self):
        self.artifact.write_text('{"passed":true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            MODULE.verify(self.manifest)

    def test_missing_artifact_fails(self):
        self.artifact.unlink()
        with self.assertRaises((ValueError, OSError)):
            MODULE.verify(self.manifest)

    def test_path_traversal_fails(self):
        data = json.loads(self.manifest.read_text())
        data["artifacts"][0]["path"] = "../gate.json"
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            MODULE.verify(self.manifest)

    def test_missing_policy_fails(self):
        data = json.loads(self.manifest.read_text())
        data["policy"] = ""
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "missing policy"):
            MODULE.verify(self.manifest)

    def test_duplicate_artifact_fails(self):
        data = json.loads(self.manifest.read_text())
        data["artifacts"].append(data["artifacts"][0])
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            MODULE.verify(self.manifest)

    def test_symlink_artifact_rejected_on_create(self):
        link = self.root / "link.json"
        try:
            link.symlink_to(self.artifact)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        with self.assertRaisesRegex(ValueError, "symlink"):
            MODULE.create(Namespace(
                baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
                verdict="block", artifact=[str(link)], output=str(self.root / "other.json")
            ))

    def test_empty_artifacts_rejected_on_create(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            MODULE.create(Namespace(
                baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
                verdict="block", artifact=[], output=str(self.root / "other.json")
            ))

    def test_gate_report_derives_block_and_is_hash_bound(self):
        report = self.root / "gate-report.json"
        report.write_text(json.dumps({"passed": False, "summary": "missing verify"}))
        MODULE.create(Namespace(
            baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
            verdict=None, gate_report=str(report), artifact=[str(self.artifact)],
            output=str(self.manifest)
        ))
        document = json.loads(self.manifest.read_text())
        self.assertEqual(document["verdict"], "block")
        self.assertIn("gate-report.json", [entry["path"] for entry in document["artifacts"]])
        MODULE.verify(self.manifest)
        report.write_text(json.dumps({"passed": True}))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            MODULE.verify(self.manifest)

    def test_conflicting_manual_verdict_rejected(self):
        report = self.root / "gate-report.json"
        report.write_text(json.dumps({"passed": False}))
        with self.assertRaisesRegex(ValueError, "conflicts"):
            MODULE.create(Namespace(
                baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
                verdict="pass", gate_report=str(report), artifact=[str(self.artifact)],
                output=str(self.manifest)
            ))

    def test_invalid_gate_report_fails_closed(self):
        report = self.root / "gate-report.json"
        report.write_text(json.dumps({"passed": "false"}))
        with self.assertRaisesRegex(ValueError, "boolean"):
            MODULE.create(Namespace(
                baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
                verdict=None, gate_report=str(report), artifact=[str(self.artifact)],
                output=str(self.manifest)
            ))

    def test_verifier_rejects_matching_hash_with_conflicting_verdict(self):
        report = self.root / "gate-report.json"
        report.write_text(json.dumps({"passed": False}))
        MODULE.create(Namespace(
            baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
            verdict=None, gate_report=str(report), artifact=[str(self.artifact)],
            output=str(self.manifest)
        ))
        data = json.loads(self.manifest.read_text())
        data["verdict"] = "pass"
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "gate verdict mismatch"):
            MODULE.verify(self.manifest)

    def test_noncanonical_gate_report_path_rejected(self):
        report = self.root / "report.json"
        report.write_text(json.dumps({"passed": False}))
        with self.assertRaisesRegex(ValueError, "named gate-report.json"):
            MODULE.create(Namespace(
                baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
                verdict=None, gate_report=str(report), artifact=[str(self.artifact)],
                output=str(self.manifest)
            ))

    def test_strict_rejects_manifest_without_gate_report(self):
        with self.assertRaisesRegex(ValueError, "requires gate-report"):
            MODULE.verify(self.manifest, strict=True)

    def test_strict_accepts_consistent_gate_report(self):
        report = self.root / "gate-report.json"
        report.write_text(json.dumps({"passed": False}))
        MODULE.create(Namespace(
            baseline="golden-1", candidate="candidate-2", policy="required-verify-v1",
            verdict=None, gate_report=str(report), artifact=[str(self.artifact)],
            output=str(self.manifest)
        ))
        MODULE.verify(self.manifest, strict=True)

    def test_manifest_is_not_authenticated(self):
        # The format is explicitly UNSIGNED: an attacker can rewrite artifact
        # and digest together. This is a limitation, not an expected failure.
        self.artifact.write_text("forged", encoding="utf-8")
        data = json.loads(self.manifest.read_text())
        data["artifacts"][0]["sha256"] = MODULE.sha256(self.artifact)
        self.manifest.write_text(json.dumps(data))
        MODULE.verify(self.manifest)


if __name__ == "__main__":
    unittest.main()
