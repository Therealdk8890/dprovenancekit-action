# 60-second killer demo: evals PASS, path FAIL

**Front door category:** regression testing for AI agent execution paths.

This folder is the stranger-friendly proof for the
[DProvenanceKit regression gate](https://github.com/marketplace/actions/dprovenancekit-regression-gate).

## The visceral contrast

Same intentional bug: the agent drops `plan` + `verify`. The final answer can still look fine.

| Check | Result |
| --- | --- |
| Output / snapshot test | **PASS** |
| LLM-as-judge / eval | **PASS** |
| OpenTelemetry / LangSmith monitoring | **PASS** |
| DProvenanceKit execution-path gate | **FAIL** — `verify` disappeared |

That gap is why this exists. Provenance and cryptographic attestation are how you later prove the path that shipped — they are not the first sentence.

## What CI does here

1. Records a **golden** path: `retrieve → plan → verify → answer`
2. Gates a matching candidate → **pass**
3. Gates a **regressed** candidate that drops `plan` + `verify` → **fail**

No DProvenanceKit cloud account. No API keys. Local SQLite only.

## Fork / run

```bash
git clone https://github.com/Therealdk8890/dprovenancekit-action.git
cd dprovenancekit-action
```

On GitHub: **Actions → “Synthetic regression demo” → Run workflow** (workflow is already on `main`).

Or push any commit — the workflow runs on push/PR.

## Where the intentional bug is

In [`agent.py`](agent.py):

- `run_golden()` calls `verify(...)` (the compliance-relevant step).
- `run_regressed()` skips `plan` and `verify` on purpose.

## Run locally

```bash
python -m pip install 'dprovenancekit==0.7.0'
python examples/synthetic-regression/record_traces.py
```

## Next

- Keep LangSmith / OTel for dashboards — run this gate beside them.
- Compare page: https://dprovenance.dev/compare/dprovenancekit-vs-langsmith/
- Attestation / audit-ready proof: Swift Secure Enclave docs in `Therealdk8890/DProvenanceKit`; Python `pip install 'dprovenancekit[crypto]'`
