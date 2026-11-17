# Evidence-based competitive demonstration

## Purpose

Demonstrate DProvenanceKit's **instrumented-path regression gate** without claiming that other evaluation platforms cannot implement equivalent checks.

This repository's observability-contrast example uses **mock** output/LLM-evaluation/OTel-style checks. It does **not** invoke LangSmith, Braintrust, Langfuse, or a production OpenTelemetry collector. A mock passing check is not evidence that a named competitor would miss the regression.

## What the current demonstration establishes

- The synthetic baseline contains a required `verify` step.
- The candidate omits that instrumented step.
- The DPK path gate can identify the change and return a failing verdict.
- The receipt evaluator can identify missing required evidence as `incomplete`.

It does not establish that DPK captures uninstrumented behavior, that the baseline is objectively correct, that attestation proves factual truth, or that other vendors lack deterministic tool-call checks.

## Required next acceptance tests

1. **Blocking CI:** Add an isolated workflow using `fail-on-regression: true` and a missing required step. Confirm the required check exits nonzero and a matching baseline exits zero. Keep the existing green meta-test separately.
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
- Do not advertise the broader Cloud or NobodySystems control planes as delivered by this Action.

## Release checklist

- [ ] Real blocking red CI and passing green CI demonstrated
- [ ] Exact action and SDK versions pinned
- [ ] Versioned release-evidence schema specified
- [ ] Positive and tampering/missing-field verifier tests
- [ ] Swift/Python production-engine parity evidence
- [ ] Public claims reconciled with demonstrated behavior
- [ ] Security and release review before merging

## Preliminary manifest verifier (implemented on this PR branch)

Create a manifest with `python scripts/release_evidence.py create --baseline BASE --candidate CAND --policy POLICY --gate-report gate-report.json --artifact evidence.json --output manifest.json`. Run `python scripts/release_evidence.py verify manifest.json --strict` to require a hash-bound `gate-report.json` with a boolean `passed` value consistent with the manifest verdict. Files must reside within the manifest directory.

**Trust boundary:** `--strict` means gate-report presence, local hash integrity, and verdict consistency. It **does not** verify a signature, trusted producer identity, gate-report provenance, policy content or completeness. Do not describe this as signed evidence or an authenticated release decision. A future signed envelope and pinned trust root are separate acceptance gates.
