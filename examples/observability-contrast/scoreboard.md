# Observability-PASS / DPK-FAIL scoreboard

| Check | Baseline | Regressed (verify dropped) |
| --- | --- | --- |
| Output test | PASS | PASS |
| LLM eval | PASS | PASS |
| Mock OTel/LangSmith-style | PASS | PASS |
| DPK path gate | PASS | **FAIL** |
| DPK Verification Receipt | PASS | **FAIL (incomplete)** |

Regenerate live:

```bash
pip install 'dprovenancekit==0.7.0'
python examples/observability-contrast/run_scoreboard.py
```
