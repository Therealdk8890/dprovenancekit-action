#!/usr/bin/env python3
"""DPK release evidence v1: local SHA-256 artifact binding, not signed attestation.

Usage:
  python scripts/release_evidence.py create --baseline BASE --candidate CAND \
      --policy POLICY --verdict pass|block --artifact PATH --output manifest.json
  python scripts/release_evidence.py verify manifest.json

This is a preliminary, stdlib-only evidence manifest. It cannot authenticate
who created the manifest: use a separately trusted signing mechanism for that.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

FORMAT = "dpk-release-evidence-v1"
MAX_BYTES = 100 * 1024 * 1024


def sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("artifact must be a regular, non-symlink file")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("artifact exceeds size limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    base = output.parent
    entries = []
    for raw in args.artifact:
        original = Path(raw)
        if original.is_symlink():
            raise ValueError("artifact must not be a symlink")
        path = original.resolve(strict=True)
        if path == output:
            raise ValueError("output manifest cannot be its own artifact")
        relative = path.relative_to(base).as_posix()
        if not relative or relative.startswith("../"):
            raise ValueError("artifacts must be inside manifest directory")
        entries.append({"path": relative, "sha256": sha256(path)})
    if len({e["path"] for e in entries}) != len(entries):
        raise ValueError("duplicate artifact path")
    if not entries:
        raise ValueError("at least one artifact is required")
    if getattr(args, "gate_report", None):
        report_path = Path(args.gate_report)
        if report_path.is_symlink():
            raise ValueError("gate report must not be a symlink")
        report_path = report_path.resolve(strict=True)
        if report_path == output:
            raise ValueError("gate report cannot be output manifest")
        try:
            report_relative = report_path.relative_to(base).as_posix()
        except ValueError as exc:
            raise ValueError("gate report must be inside manifest directory") from exc
        if report_relative in {entry["path"] for entry in entries}:
            raise ValueError("gate report must not duplicate an artifact")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or type(report.get("passed")) is not bool:
            raise ValueError("gate report requires a boolean passed field")
        expected = "pass" if report["passed"] else "block"
        if args.verdict and args.verdict != expected:
            raise ValueError("supplied verdict conflicts with gate report")
        verdict = expected
        entries.append({"path": report_relative, "sha256": sha256(report_path)})
    else:
        verdict = args.verdict
        if not verdict:
            raise ValueError("provide --gate-report or --verdict")
    document = {
        "format": FORMAT,
        "baseline": args.baseline,
        "candidate": args.candidate,
        "policy": args.policy,
        "verdict": verdict,
        "artifacts": sorted(entries, key=lambda e: e["path"]),
    }
    output.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify(path: Path) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {
        "format", "baseline", "candidate", "policy", "verdict", "artifacts"
    }:
        raise ValueError("unknown or missing manifest fields")
    if manifest["format"] != FORMAT or manifest["verdict"] not in ("pass", "block"):
        raise ValueError("unsupported manifest format or verdict")
    for key in ("baseline", "candidate", "policy"):
        if not isinstance(manifest[key], str) or not manifest[key].strip():
            raise ValueError(f"missing {key}")
    entries = manifest["artifacts"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("at least one artifact is required")
    seen = set()
    root = path.resolve().parent
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("invalid artifact entry")
        rel = entry["path"]
        digest = entry["sha256"]
        if not isinstance(rel, str) or not rel or "\\" in rel or rel.startswith("/"):
            raise ValueError("invalid artifact path")
        parts = Path(rel).parts
        if any(part in (".", "..") for part in parts) or rel in seen:
            raise ValueError("unsafe or duplicate artifact path")
        seen.add(rel)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid digest")
        target = root.joinpath(*parts)
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("artifact escapes manifest directory")
        if sha256(target) != digest:
            raise ValueError(f"artifact hash mismatch: {rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    for key in ("baseline", "candidate", "policy"):
        make.add_argument("--" + key, required=True)
    make.add_argument("--verdict", choices=("pass", "block"))
    make.add_argument("--gate-report", help="DPK gate JSON report; derive verdict from passed and hash-bind report")
    make.add_argument("--artifact", action="append", required=True)
    make.add_argument("--output", required=True)
    check = sub.add_parser("verify")
    check.add_argument("manifest")
    args = parser.parse_args()
    try:
        if args.command == "create":
            create(args)
        else:
            verify(Path(args.manifest))
        print("release evidence: OK")
        return 0
    except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"release evidence: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
