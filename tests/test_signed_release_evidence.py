"""Ed25519 evidence signature acceptance and tamper tests.

Requires the optional ``cryptography`` package; skipped when it is not installed
so the core suite stays standard-library only.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

HAVE_CRYPTOGRAPHY = importlib.util.find_spec("cryptography") is not None

if HAVE_CRYPTOGRAPHY:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(SCRIPTS))
    from release_evidence import create
    from signed_release_evidence import sign, verify


@unittest.skipUnless(HAVE_CRYPTOGRAPHY, "cryptography is not installed")
class SignedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "evidence.json"
        self.artifact.write_text('{"event":"verify"}')
        self.report = self.root / "gate-report.json"
        self.report.write_text('{"passed":true}')
        self.manifest = self.root / "manifest.json"
        create(Namespace(baseline="golden", candidate="candidate", policy="policy-v1",
                         verdict=None, gate_report=str(self.report),
                         artifact=[str(self.artifact)], output=str(self.manifest)))
        self.key = Ed25519PrivateKey.generate()
        self.private = self.root / "private.pem"
        self.public = self.root / "trusted-public.pem"
        self.private.write_bytes(self.key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()))
        self.public.write_bytes(self.key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo))
        self.signature = self.root / "manifest.sig.json"
        sign(self.manifest, self.private, self.signature)

    def test_signed_evidence_verifies(self):
        verify(self.manifest, self.signature, self.public)

    def test_tampered_manifest_rejected(self):
        data = json.loads(self.manifest.read_text())
        data["candidate"] = "different"
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(InvalidSignature):
            verify(self.manifest, self.signature, self.public)

    def test_tampered_artifact_rejected(self):
        self.artifact.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify(self.manifest, self.signature, self.public)

    def test_untrusted_signing_key_rejected(self):
        other = Ed25519PrivateKey.generate().public_key()
        self.public.write_bytes(other.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo))
        with self.assertRaises(InvalidSignature):
            verify(self.manifest, self.signature, self.public)

    def test_tampered_signature_rejected(self):
        data = json.loads(self.signature.read_text())
        data["signature"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        self.signature.write_text(json.dumps(data))
        with self.assertRaises(InvalidSignature):
            verify(self.manifest, self.signature, self.public)


if __name__ == "__main__":
    unittest.main()
