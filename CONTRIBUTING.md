# Contributing

Thanks for your interest in improving the DProvenanceKit GitHub Action.

## Development setup

The Action's scripts use the Python standard library only. The path gate also
needs the `dprovenancekit` package that `install-spec` installs at run time.

```bash
python -m pip install 'dprovenancekit==0.11.0'   # only needed for path-mode demos
python -m compileall -q .
python -m unittest discover -s tests -v
```

Run the local demos:

```bash
python examples/observability-contrast/run_scoreboard.py
DPROV_RECEIPT_PATH=fixtures/verification-receipt/verified.json python receipt_gate.py
```

## Guidelines

- Keep `gate-mode: path` and `gate-mode: receipt` input and output names
  backward compatible.
- Fail closed: malformed input or an unexpected tool result must fail the gate,
  never pass it.
- Treat trace- and receipt-derived text as untrusted. Escape it before writing
  to `$GITHUB_OUTPUT`, `$GITHUB_STEP_SUMMARY`, PR comments, or log lines, and
  pass values into `run:` scripts through `env:` rather than `${{ }}` expansion.
- Pin third-party actions to full commit SHAs with a version comment.
- Re-sync `fixtures/verification-receipt/` from DProvenanceKit rather than
  editing the goldens by hand (see `fixtures/verification-receipt/SYNC_SOURCE.md`).
- Add a focused test for every behavior change.

## Reporting security issues

Please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
