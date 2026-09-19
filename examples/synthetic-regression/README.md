# 60-second synthetic regression demo

This folder is the stranger-friendly front door for the
[DProvenanceKit regression gate](https://github.com/marketplace/actions/dprovenancekit-regression-gate).

## What you will see

1. A tiny agent records a **golden** decision path: `retrieve → plan → verify → answer`.
2. CI gates a matching candidate → **pass**.
3. CI gates a **regressed** candidate that drops `plan` + `verify` → **fail** (this is the proof the Action works).

No DProvenanceKit cloud account. No API keys. Local SQLite only.

## Fork / clone path

```bash
git clone https://github.com/Therealdk8890/dprovenancekit-action.git
cd dprovenancekit-action
```

Copy [`github-workflow.yml`](github-workflow.yml) to `.github/workflows/synthetic-regression.yml` in this repo (or your fork), then:

**Actions → “Synthetic regression demo” → Run workflow**.

(Editing files under `.github/workflows/` requires a GitHub token with the `workflow` scope; the demo agent and recorder do not.)

## Where the intentional bug is

In [`agent.py`](agent.py):

- `run_golden()` calls `verify(...)` (the compliance-relevant step).
- `run_regressed()` skips `plan` and `verify` on purpose.

The workflow asserts the gate **passes** the matching candidate and **fails** the regressed one.

## Run locally

```bash
python -m pip install 'dprovenancekit==0.7.0'
python examples/synthetic-regression/record_traces.py
```

## Next: attestation / audit proof

This demo proves **distribution** (CI refuses a drifted path). Cryptographic attestation and
audit-ready proof bundles are covered in the product SDKs and the comparison page:

- https://dprovenance.dev/compare/dprovenancekit-vs-langsmith/
- Swift attestation docs in `Therealdk8890/DProvenanceKit`
- Python: `pip install 'dprovenancekit[crypto]'` (MVP software attestation)
