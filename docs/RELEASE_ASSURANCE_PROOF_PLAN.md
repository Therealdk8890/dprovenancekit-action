# Release assurance proof plan

## Purpose

Demonstrate DProvenanceKit's **instrumented-path regression gate** without claiming that other evaluation platforms cannot implement equivalent checks.

This repository's observability-contrast example uses **mock** output/LLM-evaluation/OTel-style checks. It does **not** invoke LangSmith, Braintrust, Langfuse, or a production OpenTelemetry collector. A mock passing check is not evidence that a named product would miss the regression.

## What the current demonstration establishes

- The synthetic baseline contains a required `verify` step.
- The candidate omits that instrumented step.
- The DPK path gate can identify the change and return a failing verdict.
- The receipt evaluator can identify missing required evidence as `incomplete`.

It does not establish that DPK captures uninstrumented behavior, that the baseline is objectively correct, that attestation proves factual truth, or that other vendors lack deterministic tool-call checks.

## Required next acceptance tests

1. **Blocking CI:** An isolated, manually triggered workflow (`.github/workflows/blocking-regression-proof.yml`) runs `fail-on-regression: true` on a missing required step alongside a matching-baseline control job. Recorded run on `main` at `6a73346` (2026-11-22, dprovenancekit 0.9.2): [44997217501](https://github.com/Therealdk8890/dprovenancekit-action/actions/runs/44997217501). `baseline-must-pass` succeeded and `regression-must-block` failed at the gate step with "Regression gate failed" after the candidate dropped the `plan.*` and `verify.*` steps. The engine reported severity `none` (it does not classify these steps as critical); the job blocked because `allow-divergent` is false and `max-level` is `none`. Keep the existing green meta-test separately.
2. **Version reproducibility:** Pin the Python SDK and Action revision in the demonstration; record the exact commands, fixture digests, and CI run links.
3. **Release-evidence contract:** Produce a versioned machine-readable record binding baseline/candidate identifiers, comparison policy and evaluator versions, findings, verdict, and artifact hashes. Define which fields are signed, and fail closed on malformed or mismatched bindings.
4. **Cross-language parity:** Run the shared structural-alignment vectors against both production Swift and Python engines. Check exact verdicts, ordering, tie breaks, and negative/adversarial cases.
5. **Independent verification:** Verify a supported evidence bundle with a separately pinned trusted key, and explicitly report any unverified or missing provenance fields.
6. **Compatibility:** Document Python/Swift feature differences and prove compatibility across the released SDK and Action versions.

## Positioning

DPK complements LangSmith, Braintrust, Langfuse, and other observability/evaluation systems. Its potential advantage is a cohesive local-first workflow for structural path comparison, release enforcement, versioned history, and portable integrity evidence. These individual capabilities are not exclusive to DPK.

## Scope and trust boundaries

- `verified` means the specified recorded-path and integrity checks passed, not that an AI conclusion is true.
- The recorder sees instrumented execution, not hidden model reasoning.
- The CI gate is not an external runtime sandbox or containment boundary.
- Python software-key attestation and Swift Secure Enclave/proof-pack capabilities are not interchangeable.
- Experimental alignment and repository-history APIs must be identified by their supported release versions.
- Do not describe hosted control planes or other products as delivered by this Action; there is no DProvenanceKit-hosted service.

## Release checklist

- [x] Real blocking red CI and passing green CI demonstrated ([run](https://github.com/Therealdk8890/dprovenancekit-action/actions/runs/44997217501))
- [ ] Exact action and SDK versions pinned
- [ ] Versioned release-evidence schema specified
- [ ] Positive and tampering/missing-field verifier tests
- [ ] Swift/Python production-engine parity evidence
- [ ] Public claims reconciled with demonstrated behavior
- [ ] Security and release review before merging

## Preliminary manifest verifier

Create a manifest with `python scripts/release_evidence.py create --baseline BASE --candidate CAND --policy POLICY --gate-report gate-report.json --artifact evidence.json --output manifest.json`. Run `python scripts/release_evidence.py verify manifest.json --strict` to require a hash-bound `gate-report.json` with a boolean `passed` value consistent with the manifest verdict. Files must reside within the manifest directory.

**Trust boundary:** `--strict` means gate-report presence, local hash integrity, and verdict consistency. It **does not** verify a signature, trusted producer identity, gate-report provenance, policy content or completeness. Do not describe this as signed evidence or an authenticated release decision. A future signed envelope and pinned trust root are separate acceptance gates.

## Signing

Signing is not part of this release. The unsigned manifest above only proves local hash consistency: anyone who can rewrite an artifact can also rewrite its digest. Authenticated release evidence (likely keyless signing through GitHub OIDC/Sigstore) is tracked separately and remains a future acceptance gate.
