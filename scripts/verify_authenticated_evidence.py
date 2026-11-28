#!/usr/bin/env python3
"""Experimental verifier: trusted Cosign executable, identity and immutable local bundle."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from release_evidence import read_regular, verify_manifest_bytes


def check(manifest: Path, bundle: Path, *, identity: str, issuer: str,
          baseline: str, candidate: str, policy: str, require_pass: bool = False) -> None:
    if not all(x.strip() for x in (identity, issuer, baseline, candidate, policy)):
        raise ValueError("explicit identity, issuer and release expectations required")
    # Verify the exact bytes later interpreted by the local verifier.
    # Caller must ensure bundle directory is not concurrently writable.
    original = read_regular(manifest)
    bundle_bytes = read_regular(bundle)
    # Authenticate private snapshots, not attacker-replaceable input paths.
    with tempfile.TemporaryDirectory(prefix="dpk-evidence-") as directory:
        snapshot = Path(directory) / "manifest.json"
        signature = Path(directory) / "bundle.json"
        snapshot.write_bytes(original)
        signature.write_bytes(bundle_bytes)
        subprocess.run(
            ["cosign", "verify-blob", "--bundle", str(signature),
             "--certificate-identity", identity, "--certificate-oidc-issuer", issuer,
             str(snapshot)],
            check=True, timeout=120,
        )
    if read_regular(manifest) != original:
        raise ValueError("manifest changed during signature verification")
    verify_manifest_bytes(original, manifest.resolve().parent, strict=True)
    if read_regular(manifest) != original:
        raise ValueError("manifest changed during artifact verification")
    doc = json.loads(original)
    for key, expected in (("baseline", baseline), ("candidate", candidate), ("policy", policy)):
        if doc[key] != expected:
            raise ValueError(f"unexpected {key}")
    if require_pass and doc["verdict"] != "pass":
        raise ValueError("release blocked by evidence verdict")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    for name in ("identity", "issuer", "baseline", "candidate", "policy"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    try:
        check(**vars(args))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        print(f"authenticated evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    print("authenticated evidence: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
