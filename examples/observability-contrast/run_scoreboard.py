#!/usr/bin/env python3
"""Print the observability-PASS / DPK-FAIL five-row scoreboard.

Runs mock output / LLM-eval / OTel-style checkers on baseline + regressed
agent answers (all PASS), then DPK path gate + Verification Receipt gate
(baseline PASS, regressed FAIL).

Requires: pip install 'dprovenancekit==0.7.0' (same pin as the Action).
Stdlib + that install-spec only — no paid SaaS.

Exit 0 when the contrast holds (mocks PASS on both; DPK FAIL only on
regressed). Exit 1 if the demo itself is broken.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DB = HERE / "demo-traces.sqlite"
RECEIPT_VERIFIED = REPO / "fixtures" / "verification-receipt" / "verified.json"
RECEIPT_INCOMPLETE = REPO / "fixtures" / "verification-receipt" / "incomplete.json"
RECEIPT_GATE = REPO / "receipt_gate.py"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

from agent import run_baseline, run_regressed  # noqa: E402
from mock_llm_eval import all_passed as llm_all_passed  # noqa: E402
from mock_llm_eval import evaluate as llm_evaluate  # noqa: E402
from mock_observability import all_passed as obs_all_passed  # noqa: E402
from mock_observability import evaluate as obs_evaluate  # noqa: E402


def _cell(ok: bool, *, fail_label: str = "FAIL") -> str:
    return "PASS" if ok else f"**{fail_label}**"


def _parse_gate_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Last JSON object on stdout
    matches = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL))
    for match in reversed(matches):
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


def _dpk_cli() -> list[str]:
    """Resolve the dprovenancekit console script next to this interpreter."""
    bindir = Path(sys.executable).resolve().parent
    candidate = bindir / "dprovenancekit"
    if candidate.is_file():
        return [str(candidate)]
    # Fallback: invoke console entry via python -c (no __main__.py on 0.7.0)
    return [
        sys.executable,
        "-c",
        "import sys; from dprovenancekit.cli import main; sys.argv = ['dprovenancekit'] + sys.argv[1:]; raise SystemExit(main())",
    ]


def _run_path_gate(candidate_context: str) -> bool:
    """Return True when the path gate passed."""
    cmd = _dpk_cli() + [
        "gate",
        "--db",
        str(DB),
        "--golden-context",
        "golden",
        "--candidate-context",
        candidate_context,
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    report = _parse_gate_json(proc.stdout) or _parse_gate_json(proc.stderr)
    if "passed" in report:
        return bool(report["passed"])
    if "matching" in report:
        return bool(report["matching"])
    # Fall back to CLI exit code (0 = pass, 1 = regression)
    return proc.returncode == 0


def _parse_github_output(text: str) -> dict[str, str]:
    """Parse GITHUB_OUTPUT heredoc format (key<<DELIM ... DELIM)."""
    out: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line:
            key, delim = line.split("<<", 1)
            key = key.strip()
            delim = delim.strip()
            i += 1
            chunks: list[str] = []
            while i < len(lines) and lines[i] != delim:
                chunks.append(lines[i])
                i += 1
            out[key] = "\n".join(chunks)
        i += 1
    return out


def _run_receipt_gate(receipt_path: Path) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fh:
        out_path = fh.name
    env = dict(os.environ)
    env["DPROV_RECEIPT_PATH"] = str(receipt_path)
    env["DPROV_FAIL_ON_RECEIPT"] = "false"
    env["GITHUB_OUTPUT"] = out_path
    subprocess.run(
        [sys.executable, str(RECEIPT_GATE)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        check=False,
    )
    raw = Path(out_path).read_text(encoding="utf-8")
    Path(out_path).unlink(missing_ok=True)
    parsed = _parse_github_output(raw)
    status = parsed.get("receipt-status", "unknown")
    passed = parsed.get("passed", "false").lower() == "true"
    if "report-json" in parsed:
        try:
            report = json.loads(parsed["report-json"])
            status = str(report.get("status", status))
            passed = bool(report.get("passed", passed))
        except json.JSONDecodeError:
            pass
    return passed, status


def _record_traces() -> None:
    subprocess.run(
        [sys.executable, str(HERE / "record_traces.py")],
        check=True,
        cwd=str(HERE),
    )


def main() -> int:
    baseline_answer = run_baseline()
    regressed_answer = run_regressed()

    # --- Mock checkers (PASS on both; they never look at path shape) ---
    base_obs = obs_evaluate(
        baseline_answer,
        span_names=["retrieve", "plan", "verify", "answer"],
    )
    reg_obs = obs_evaluate(
        regressed_answer,
        span_names=["retrieve", "answer"],  # incomplete path — still "trace exists"
    )
    base_llm = llm_evaluate(baseline_answer)
    reg_llm = llm_evaluate(regressed_answer)

    output_base = bool(baseline_answer and baseline_answer.strip())
    output_reg = bool(regressed_answer and regressed_answer.strip())
    llm_base = llm_all_passed(base_llm)
    llm_reg = llm_all_passed(reg_llm)
    otel_base = obs_all_passed(base_obs)
    otel_reg = obs_all_passed(reg_obs)

    # --- DPK path gate ---
    _record_traces()
    path_base = _run_path_gate("baseline")
    path_reg = _run_path_gate("regressed")

    # --- DPK Verification Receipt (vendored 1C fixtures; verify dropped → incomplete) ---
    receipt_base, receipt_base_status = _run_receipt_gate(RECEIPT_VERIFIED)
    receipt_reg, receipt_reg_status = _run_receipt_gate(RECEIPT_INCOMPLETE)

    rows = [
        ("Output test", _cell(output_base), _cell(output_reg)),
        ("LLM eval", _cell(llm_base), _cell(llm_reg)),
        ("Mock OTel/LangSmith-style", _cell(otel_base), _cell(otel_reg)),
        (
            "DPK path gate",
            _cell(path_base),
            _cell(path_reg, fail_label="FAIL"),
        ),
        (
            "DPK Verification Receipt",
            _cell(receipt_base),
            (
                "PASS"
                if receipt_reg
                else f"**FAIL ({receipt_reg_status or 'incomplete'})**"
            ),
        ),
    ]

    print("")
    print("## Observability-PASS / DPK-FAIL scoreboard")
    print("")
    print("| Check | Baseline | Regressed (verify dropped) |")
    print("| --- | --- | --- |")
    for name, b, r in rows:
        print(f"| {name} | {b} | {r} |")
    print("")
    print(
        f"baseline_answer={baseline_answer!r}  regressed_answer={regressed_answer!r}"
    )
    print(
        f"receipt baseline={receipt_base_status}  regressed={receipt_reg_status}"
    )
    print("")
    print(
        "Sell the failure: mocks stay green; DPK path gate + receipt catch the missing verify."
    )
    print(
        "Verified ≠ claim true. DPK is path/provenance control — complementary to LangSmith."
    )

    contrast_ok = (
        output_base
        and output_reg
        and llm_base
        and llm_reg
        and otel_base
        and otel_reg
        and path_base
        and (not path_reg)
        and receipt_base
        and (not receipt_reg)
    )
    if not contrast_ok:
        print(
            "ERROR: expected contrast broken — mocks PASS both; "
            "DPK FAIL only on regressed."
        )
        print(
            f"debug: path_base={path_base} path_reg={path_reg} "
            f"receipt_base={receipt_base} receipt_reg={receipt_reg}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
