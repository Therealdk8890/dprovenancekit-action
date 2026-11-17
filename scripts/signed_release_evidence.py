#!/usr/bin/env python3
"""Sign/verify DPK evidence manifests using Ed25519 and an explicit trust root.

Install: python -m pip install 'cryptography>=42,<47'
Signature covers exact manifest bytes, including its trailing newline.
Verification also runs the strict local manifest and gate-report checks.
Never supply an untrusted public key from inside the evidence bundle.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from release_evidence import verify as verify_manifest

SCHEMA = "dpk-release-evidence-signature-v1"


def sign(manifest: Path, private_key_path: Path, output: Path) -> None:
    verify_manifest(manifest, strict=True)
    if output.resolve() == manifest.resolve():
        raise ValueError("signature output must not overwrite manifest")
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("expected Ed25519 private key")
    signature = private_key.sign(manifest.read_bytes())
    envelope = {"format": SCHEMA, "algorithm": "Ed25519", "signature": base64.b64encode(signature).decode("ascii")}
    output.write_text(json.dumps(envelope, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify(manifest: Path, signature_path: Path, trusted_public_key_path: Path) -> None:
    # Signature authenticity is checked against the caller's out-of-band trust root.
    public_key = serialization.load_pem_public_key(trusted_public_key_path.read_bytes())
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("expected Ed25519 public key")
    envelope = json.loads(signature_path.read_text(encoding="utf-8"))
    if not isinstance(envelope, dict) or set(envelope) != {"format", "algorithm", "signature"}:
        raise ValueError("invalid signature envelope")
    if envelope["format"] != SCHEMA or envelope["algorithm"] != "Ed25519":
        raise ValueError("unsupported signature format")
    raw = base64.b64decode(envelope["signature"], validate=True)
    if len(raw) != 64:
        raise ValueError("invalid signature length")
    public_key.verify(raw, manifest.read_bytes())
    verify_manifest(manifest, strict=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    signer = sub.add_parser("sign")
    signer.add_argument("manifest")
    signer.add_argument("--private-key", required=True)
    signer.add_argument("--output", required=True)
    checker = sub.add_parser("verify")
    checker.add_argument("manifest")
    checker.add_argument("--signature", required=True)
    checker.add_argument("--trusted-public-key", required=True)
    args = parser.parse_args()
    try:
        if args.command == "sign":
            sign(Path(args.manifest), Path(args.private_key), Path(args.output))
        else:
            verify(Path(args.manifest), Path(args.signature), Path(args.trusted_public_key))
        print("signed release evidence: OK")
        return 0
    except (ValueError, OSError, TypeError, KeyError, InvalidSignature) as exc:
        print(f"signed release evidence: FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
