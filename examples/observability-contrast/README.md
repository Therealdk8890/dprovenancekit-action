# Why not just observability?

Your agent run looks successful. Output tests, LLM-evals, and OTel/LangSmith-style
checks all stay green — HTTP 200, answer non-empty, “a trace exists.” Meanwhile the
required **verify** decision step was dropped. That is the bug buyers actually fear.
DProvenanceKit’s path gate (and Verification Receipt) fail with evidence. Keep
LangSmith for dashboards; add DPK for path/provenance control. **Verified ≠ claim
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
pip install 'dprovenancekit==0.7.0'
python examples/observability-contrast/run_scoreboard.py
```

Or in CI: **Actions → “Observability contrast demo”**. The log prints mock PASSes,
then DPK FAILs the job on the verify-dropped run — that red X *is* the demo.

Sister fixture (path gate only, green meta-assert): [`../synthetic-regression/`](../synthetic-regression/).
