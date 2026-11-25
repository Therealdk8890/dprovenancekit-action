# Why not just observability?

The demo agent run looks successful. Mock output tests, LLM-evals, and
OTel/LangSmith-style checks all stay green — HTTP 200, answer non-empty, “a trace
exists.” Meanwhile the required **verify** decision step was dropped.
DProvenanceKit’s path gate (and Verification Receipt) report that regression with
evidence. The checkers here are small local mocks written for this demo, not the
real LangSmith or OpenTelemetry products; DPK is meant to run alongside those
tools for path/provenance control. **Verified ≠ claim
true** — cryptography protects integrity of a recorded path, not factual truth of
the answer text.

## Scoreboard

| Check | Baseline | Regressed (verify dropped) |
| --- | --- | --- |
| Output test | PASS | PASS |
| LLM eval | PASS | PASS |
| Mock OTel/LangSmith-style | PASS | PASS |
| DPK path gate | PASS | **FAIL** |
| DPK Verification Receipt | PASS | **FAIL (incomplete)** |

## How to run (60 seconds)

```bash
pip install 'dprovenancekit==0.11.0'
python examples/observability-contrast/run_scoreboard.py
```

Or in CI: **Actions → “Observability contrast demo”**. The log prints the mock
PASSes, then the DPK gates report `passed=false` on the verify-dropped run. The
workflow asserts that contrast, so the job itself stays green.

Sister fixture (path gate only, green meta-assert): [`../synthetic-regression/`](../synthetic-regression/).
