import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from release_evidence import create
from verify_authenticated_evidence import check


class AuthenticatedEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.manifest = root / "manifest.json"
        self.bundle = root / "manifest.sigstore.json"
        self.bundle.write_text("{}")
        self.report = root / "gate-report.json"
        self.artifact = root / "trace.json"
        self.artifact.write_text("{}")
        self.options = dict(identity="https://github.com/example/repo/.github/workflows/release.yml@refs/heads/main",
                            issuer="https://token.actions.githubusercontent.com",
                            baseline="a", candidate="b", policy="p", require_pass=True)
        self.make(True)

    def make(self, passed):
        self.report.write_text(json.dumps({"passed": passed}))
        create(Namespace(output=str(self.manifest), artifact=[str(self.artifact)],
                         gate_report=str(self.report), verdict=None,
                         baseline="a", candidate="b", policy="p"))

    @patch("verify_authenticated_evidence.subprocess.run")
    def test_valid_context(self, run):
        check(self.manifest, self.bundle, **self.options)
        args = run.call_args.args[0]
        self.assertIn(self.options["identity"], args)
        self.assertIn(self.options["issuer"], args)
        self.assertTrue(run.call_args.kwargs["check"])

    @patch("verify_authenticated_evidence.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cosign"))
    def test_signature_failure(self, run):
        with self.assertRaises(subprocess.CalledProcessError):
            check(self.manifest, self.bundle, **self.options)

    @patch("verify_authenticated_evidence.subprocess.run")
    def test_context_mismatch(self, run):
        for field in ("baseline", "candidate", "policy"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"unexpected {field}"):
                check(self.manifest, self.bundle, **(self.options | {field: "wrong"}))

    @patch("verify_authenticated_evidence.subprocess.run")
    def test_block_not_release_approval(self, run):
        self.make(False)
        with self.assertRaisesRegex(ValueError, "release blocked"):
            check(self.manifest, self.bundle, **self.options)
        check(self.manifest, self.bundle, **(self.options | {"require_pass": False}))

    @patch("verify_authenticated_evidence.subprocess.run")
    def test_tampered_artifact(self, run):
        self.artifact.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            check(self.manifest, self.bundle, **self.options)


    @patch("verify_authenticated_evidence.subprocess.run")
    def test_artifacts_are_checked_against_authenticated_manifest_bytes(self, run):
        import hashlib

        from release_evidence import read_regular

        original = json.loads(self.manifest.read_text())
        self.artifact.write_text("tampered")
        forged = json.loads(json.dumps(original))
        for entry in forged["artifacts"]:
            if entry["path"] == "trace.json":
                entry["sha256"] = hashlib.sha256(self.artifact.read_bytes()).hexdigest()

        def substituted_read(path):
            if path == self.manifest:
                return json.dumps(forged).encode("utf-8")
            return read_regular(path)

        # Model a transient substituted manifest seen only by the artifact
        # verifier. It must never parse a second manifest after authentication.
        with patch("release_evidence.read_regular", side_effect=substituted_read):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                check(self.manifest, self.bundle, **self.options)
