# Permanent project rules

1. Preserve proven analyzer behavior, calibration-v2 formulas and Score v1
   semantics. Structural cleanup is not permission to change business meaning.
2. Delete or replace a legacy path only after the replacement passes the same
   golden, contract, adapter and integration gates.
3. Keep contracts transport-neutral. Product logic must not import FastAPI,
   persistence implementations, provider payloads or another analyzer's
   internals.
4. Keep missing, unavailable, skipped and inconclusive data distinct from a
   measured score of zero.
5. External projects belong behind replaceable adapters or process boundaries;
   do not copy upstream source into the production package.
6. Every new boundary needs deterministic serialization, focused tests and a
   documented compatibility decision.
7. Use the workflow: explore → plan → improve → implement → verify → review.
8. Keep credentials out of contracts, logs, persistence and test artifacts;
   redact provider responses before they cross a boundary.
9. Keep serious work on the dedicated task branch/worktree and inspect the
   final diff for unrelated changes before handoff.
