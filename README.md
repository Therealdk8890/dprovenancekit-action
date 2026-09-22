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
The receipt gate is **stdlib-only** and vendors Phase 0/1C golden vectors and
schemas from
[DProvenanceKit](https://github.com/Therealdk8890/DProvenanceKit) (evaluator
aligned to Phase 1C `VerificationReceiptProjector`). This is an
**attestation / provenance** gate — not an observability dashboard rival.

<!-- synthetic-regression-quickstart -->
## 60-second proof (fork this)

**Category:** regression testing for AI agent execution paths.

Same bug, four checkers:

| Check | Result |
| --- | --- |
| Output test | PASS |
| LLM eval | PASS |
| OTel / LangSmith | PASS |
| **DProvenanceKit path gate** | **FAIL — `verify` dropped** |

1. **Actions → “Synthetic regression demo” → Run workflow** (or push to `main`).
2. CI gates a matching run (**pass**), then a run that drops `verify` (**fail**).
3. Read [`examples/synthetic-regression/`](examples/synthetic-regression/) — intentional bug in `agent.py`.

Keep LangSmith for dashboards; add this gate for execution-path regressions. Deeper layer (attestation / audit proof): [DProvenanceKit vs LangSmith](https://dprovenance.dev/compare/dprovenancekit-vs-langsmith/).

<!-- /synthetic-regression-quickstart -->

## Verification Receipt gate (Phase 1B + 1C sync)

Same status vocabulary and golden vectors as DProvenanceKit Phase 1C
(`claim-path-v1` projector) and CaseClarity Phase 1A. Precedence:
**tampered > incomplete > verified**.

| Status | Meaning | Default CI |
| --- | --- | --- |
| `verified` | Required steps in order **and** integrity pass | PASS |
| `incomplete` | Missing invariant evidence (e.g. no `verify` step) | FAIL |
| `tampered` | Integrity / attestation failure | FAIL |

**Verified ≠ claim objectively true.** Cryptography protects integrity of a
recorded path; it does not certify factual truth of the claim text.

JSON Schema validates structure only. The Action recomputes status from
integrity flags + invariant evaluation (`required_steps` / `must_include` /
`ordering`) — it does not trust a receipt's `status` field blindly.

### Scoreboard (vendored fixtures from DPK Phase 1C)

| Fixture | Gate |
| --- | --- |
| `fixtures/verification-receipt/verified.json` | PASS |
| `fixtures/verification-receipt/incomplete.json` | FAIL |
| `fixtures/verification-receipt/tampered.json` | FAIL |

Vectors and schemas are re-synced from `Therealdk8890/DProvenanceKit` main
(Phase 1C merge #119); see `fixtures/verification-receipt/SYNC_SOURCE.md`.

Workflow: **Actions → “Verification Receipt gate demo”** (also runs on PRs).

### Usage

```yaml
name: verification-receipt
on: pull_request

permissions:
  contents: read
  pull-requests: write

jobs:
  receipt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verification Receipt gate
        uses: Therealdk8890/dprovenancekit-action@<commit-sha>
        with:
          gate-mode: receipt
          receipt-path: path/to/verification-receipt.json
          # invariant-path: optional; defaults to vendored claim-path-v1
          # fail-on-receipt-statuses: incomplete,tampered
```

Local check (no Action runner required):

```bash
DPROV_RECEIPT_PATH=fixtures/verification-receipt/verified.json python receipt_gate.py
DPROV_RECEIPT_PATH=fixtures/verification-receipt/incomplete.json python receipt_gate.py
DPROV_RECEIPT_PATH=fixtures/verification-receipt/tampered.json python receipt_gate.py

python -m unittest tests.test_receipt_gate -v
```

Fixtures and schemas under `fixtures/verification-receipt/` are vendored from
`Therealdk8890/DProvenanceKit` main (Phase 1C goldens) — see
`fixtures/verification-receipt/SYNC_SOURCE.md`.
Do not invent a second status vocabulary or expand step types beyond
`evidence | extract | verify | claim`.

The receipt gate **complements** the path-regression gate (`gate-mode: path`);
it does not replace it.

## Recommended pins

- **Action:** pin to a **commit SHA** (preferred for supply-chain review) or a
  release tag such as `@v1.1.1` / `@v1`. Avoid floating `@main`.
  ```yaml
  uses: Therealdk8890/dprovenancekit-action@<commit-sha>   # preferred
  # uses: Therealdk8890/dprovenancekit-action@v1          # floating major — OK for demos
  ```
- **PyPI package:** the Action default `install-spec` is
  **`dprovenancekit==0.7.0`** (core gate; crypto extra not required for gating).
  Override only for deliberate upgrades.

## Usage

```yaml
name: decision-path-regression
on: pull_request

permissions:
  contents: read
  pull-requests: write   # required for the PR comment

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Produce a SQLite trace database with your golden + candidate runs.
      # (Record the candidate from this PR; restore/fetch the golden baseline.)
      - name: Record traces
        run: python scripts/record_traces.py   # your script; writes traces.sqlite

      - name: Regression gate
        uses: Therealdk8890/dprovenancekit-action@v1
        with:
          db-path: traces.sqlite
          golden-context: golden        # newest run recorded with this context id
          candidate-context: candidate  # (or pass golden-run-id / candidate-run-id)
          max-level: none          # strict: any divergence fails
          # allow-divergent: true  # tolerate per-step changes, gate only on severity
          # install-spec: dprovenancekit==0.7.0   # already the Action default
```

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `gate-mode` | `path` | `path` (decision-path regression) or `receipt` (Verification Receipt). |
| `receipt-path` | `""` | Path to a VerificationReceipt JSON. Required when `gate-mode=receipt`. |
| `invariant-path` | vendored `claim-path-v1` | Path to a VerificationInvariant JSON (receipt mode). |
| `fail-on-receipt-statuses` | `incomplete,tampered` | Receipt statuses that fail the job (receipt mode). |
| `fail-on-receipt` | `true` | Fail the job when receipt status is in `fail-on-receipt-statuses`. |
| `db-path` | `""` (required for `path`) | SQLite trace database holding both runs. |
| `golden-db` | `db-path` | SQLite db holding the golden run, if separate (e.g. a restored baseline). |
| `candidate-db` | `db-path` | SQLite db holding the candidate run, if separate. |
| `golden-run-id` | `""` | Run id of the golden (known-good) trace. Provide this **or** `golden-context`. |
| `candidate-run-id` | `""` | Run id of the candidate trace to gate. Provide this **or** `candidate-context`. |
| `golden-context` | `""` | Select the newest run with this context id as the golden — no run-id extraction needed. A context with no matching run fails the gate step loudly instead of silently passing. |
| `candidate-context` | `""` | Select the newest run with this context id as the candidate. Anomaly rules resolve it the same way. |
| `max-level` | `none` | Worst severity that still passes: `none` \| `low` \| `medium` \| `high`. |
| `allow-divergent` | `false` | Tolerate per-step changes; gate only on severity. |
| `fail-on-regression` | `true` | Fail the job when a regression is detected. |
| `comment` | `true` | Post a sticky summary comment on the PR. |
| `anomaly-rules` | `""` | Path to a JSON rules config. When set, runs the out-of-the-box anomaly rules over the candidate run. |
| `fail-on-anomaly` | `false` | Fail the job when an anomaly rule fires. |
| `install-spec` | `dprovenancekit==0.7.0` | pip requirement to install the gate from (pin a version or point at a VCS URL). |
| `python-version` | `3.x` | Python to set up. |
| `cloud-mode` | `off` | Customer **BYO** cloud ingest only: `off` \| `optional` \| `required`. There is **no** DProvenanceKit-hosted service. |
| `cloud-url` | `""` | Customer-supplied cloud base URL. **Required** when `cloud-mode` is not `off` (fail closed if empty — no default host). |
| `cloud-api-key` | `""` | API key for BYO cloud ingestion. |
| `project-id` | `""` | Project ID for BYO cloud ingest. |
| `promote-baseline` | `false` | If true and the gate passes, attempt BYO baseline promotion (still requires `cloud-url` + key + project). |
| `default-branch` | `main` | Default branch name used to enforce baseline promotion eligibility. |
| `artifacts` | `[]` | JSON array of artifacts to attach to an ingested run. |
| `artifact-paths` | `[]` | JSON array of paths to upload to the BYO cloud endpoint. |
| `upload-trace-database` | `false` | Upload the SQLite trace database as a CI artifact. |
| `github-token` | `${{ github.token }}` | Token used to post the comment. |

## Outputs

| Output | Description |
| --- | --- |
| `passed` | `true` when the active gate passed. |
| `regression-level` | Engine-assessed severity (`none` \| `low` \| `medium` \| `high`) in path mode. |
| `summary` | Human-readable gate summary. |
| `report-json` | Full gate report as a JSON string. |
| `anomaly-count` | Number of anomalies the rules fired on (`0` when `anomaly-rules` is unset). |
| `anomalies-json` | Anomaly findings as a JSON string (`{}` when `anomaly-rules` is unset). |
| `receipt-status` | Recomputed status (`verified` \| `incomplete` \| `tampered`) in receipt mode. |
| `receipt-reason` | Short reason for the recomputed status. |
| `receipt-invariant-id` | Invariant id used for evaluation. |

## Cloud ingest (customer BYO only)

Public DProvenanceKit docs do **not** offer a hosted cloud control plane. The
optional `cloud-*` inputs exist only so a customer can point the Action at
**their own** ingest endpoint.

- Default: `cloud-mode=off` — local gate only.
- If you set `cloud-mode` to `optional` or `required`, you **must** also set
  `cloud-url` to your endpoint. An empty/missing URL **fails closed** (exit 1);
  the Action will not invent `https://api.dprovenance.dev` or any other host.
- `optional` still skips on missing API key / project id / transport errors
  (warn only); `required` fails the job on those failures.

## Anomaly rules

Set `anomaly-rules` to a JSON config to also run the out-of-the-box rule library over the
candidate run. Findings surface as inline `::warning::` annotations and a job summary; set
`fail-on-anomaly: true` to also fail the job.

```json
{
  "rules": [
    { "type": "tool_drop", "required_step": "safety_check" },
    { "type": "looping", "step": "web_search", "max_repeats": 5 }
  ]
}
```

```yaml
      - uses: Therealdk8890/dprovenancekit-action@v1
        with:
          db-path: traces.sqlite
          golden-run-id: ${{ env.GOLDEN_RUN_ID }}
          candidate-run-id: ${{ env.CANDIDATE_RUN_ID }}
          anomaly-rules: .github/dprov-rules.json
          fail-on-anomaly: true
```

The same rules run anywhere without the action via `dprovenancekit anomalies --db traces.sqlite --rules rules.json [--run <id>] [--json]`.

## Baseline selection

The golden run usually comes from `main` and the candidate from the PR. Restore a baseline
database (built on `main`, cached or committed), record the PR's run into a separate database,
and select both by context id — no run-id extraction:

```yaml
      - uses: Therealdk8890/dprovenancekit-action@v1
        with:
          golden-db: baseline.sqlite
          candidate-db: candidate.sqlite
          db-path: candidate.sqlite      # still required; used as the shared default
          golden-context: my-agent       # newest my-agent run in baseline.sqlite
          candidate-context: my-agent    # newest my-agent run in candidate.sqlite
```

A context with no matching run fails the gate step loudly (exit 2) instead of silently passing.
For explicit id selection, `dprovenancekit runs --db <db> [--context <id>] [--latest]
[--format id | --json]` still lists or selects runs.

## Notes

- **Fork PRs:** `GITHUB_TOKEN` is read-only on pull requests from forks, so the comment step
  is skipped with a notice rather than failing the job. The gate verdict (and job
  pass/fail) is unaffected.
- The action reads databases in the standard type-erased format the library's stores produce.
