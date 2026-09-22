# Vendored from Therealdk8890/DProvenanceKit (main)

Synced from commit: `f6f82308ba3a06b5b1fde306df59f5caee5e6906`
(includes Phase 1C VerificationReceipt projector — merge #119 / `747fcf8ea7f1ea1eab850212739f46329a7ea64f`)

Source of truth:
- docs/VERIFICATION_RECEIPT.md
- schemas/verification-receipt.schema.json
- schemas/verification-invariant.schema.json
- fixtures/verification-receipt/{verified,incomplete,tampered}.json
- fixtures/verification-receipt/invariant-claim-path-v1.json

Re-copy when DProvenanceKit Phase 0/1C fixtures or schemas change.
Do not invent a second status vocabulary or expand step taxonomy beyond
evidence | extract | verify | claim.

Evaluator precedence (locked with DPK Phase 1C):
1. Integrity failure → tampered
2. Else invariant failure → incomplete
3. Else → verified

Invariant id: claim-path-v1. Verified ≠ claim objectively true.
