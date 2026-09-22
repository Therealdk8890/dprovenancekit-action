# DProvenanceKit regression gate — GitHub Action

DProvenanceKit records each AI agent execution as a queryable, diffable trace.
This action gates your pull requests on that record in two complementary modes:

1. **Path gate** (`gate-mode: path`, default) — compare a candidate run against a
   golden baseline; fail when the agent's **instrumented decision path**
   regresses (dropped verification step, looping tool, reordered path).
2. **Verification Receipt gate** (`gate-mode: receipt`) — evaluate a
   `VerificationReceipt` against the shared `claim-path-v1` invariant; fail when
   status is `incomplete` or `tampered`.

Both modes post a sticky PR comment with the verdict. The path gate wraps the
server-less `dprovenancekit gate` CLI (**no hosted DProvenanceKit backend**).
The receipt gate is **stdlib-only** and vendors Phase 0 fixtures/schemas from
[DProvenanceKit](https://github.com/Therealdk8890/DProvenanceKit). This is an
**attestation / provenance** gate — not an observability dashboard rival.

<!-- synthetic-regression-quickstart -->
## 60-second proof

Use the standalone demo first: **[dpk-gate-demo](https://github.com/Therealdk8890/dpk-gate-demo)** ([green run](https://github.com/Therealdk8890/dpk-gate-demo/actions/runs/35685130719)).

This Action repo still vendors the same fixture under `examples/synthetic-regression/`.

**Category:** regression testing for AI agent execution paths.

Same bug, four checkers:

| Check | Result |
| --- | --- |
| Output test | PASS |
| LLM eval | PASS |
| OTel / LangSmith | PASS |
| **DProvenanceKit path gate** | **FAIL — `verify` dropped** |

1. Open **[dpk-gate-demo Actions](https://github.com/Therealdk8890/dpk-gate-demo/actions)**.
2. CI gates a matching run (**pass**), then a run that drops `verify` (**fail**).
3. Copy `agent.py` / `record_traces.py` / `.github/workflows/gate.yml` from that repo.

Keep LangSmith for dashboards; add this gate for execution-path regressions.
<!-- /synthetic-regression-quickstart -->
