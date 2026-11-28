# Authenticated release evidence (experimental)

The unsigned v1 manifest provides hash consistency, not origin authentication.
The experimental verifier delegates signature verification to Cosign and
requires an independently configured exact certificate identity and OIDC issuer.

## Verification contract

```sh
python scripts/verify_authenticated_evidence.py manifest.json \
  --bundle manifest.sigstore.json \
  --identity 'https://github.com/OWNER/REPO/.github/workflows/release.yml@refs/heads/main' \
  --issuer https://token.actions.githubusercontent.com \
  --baseline EXPECTED_BASELINE --candidate EXPECTED_CANDIDATE \
  --policy EXPECTED_POLICY --require-pass
```

Expected values must originate from trusted release configuration, never from
the untrusted manifest. Prefer immutable commit identifiers and a policy digest.
Without --require-pass, authenticated blocked evidence can be inspected but
must not be used as deployment approval.

## Acceptance gates before production

- Pin and verify the Cosign distribution and supported bundle format.
- Produce a real keyless signature from a narrowly scoped trusted workflow.
- Verify from a separate job without signing permissions.
- Reject modified manifest, artifact, signature, wrong identity and issuer,
  wrong release context, and blocked verdict when approval is required.
- Test replay across commits and policies; define freshness requirements.
- Publish trust configuration and rotation procedures.
- Harden filesystem access against concurrent replacement or use a private
  immutable snapshot; current verifier assumes a stable directory.

Artifact hashes and the release verdict are verified against the exact authenticated manifest bytes, without reparsing the source manifest path. The stable-directory requirement still applies to artifact reads.

Unit tests mock Cosign and do not establish cryptographic interoperability.
Do not grant OIDC signing permission to untrusted pull-request code.
A signature authenticates evidence bytes, not capture completeness, semantic
correctness, policy adequacy, or runtime containment.

## Synthetic interoperability test

The branch-only synthetic Sigstore workflow signs public fixture manifests using GitHub OIDC and verifies them in a separate job without signing permission. Cosign v3.1.6 is pinned by the SHA-256 of its Linux binary. The exact test branch and workflow identity is deliberately distinct from any release signer. Never add it to production trust configuration. No release or deployment occurs, and this workflow never runs on pull requests. Passing this test establishes interoperability for these fixtures, not a production signing policy.
