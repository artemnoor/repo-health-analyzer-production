# Permanent project rules

1. We are gradually turning the existing Repository Health Analyzer into a
   modular system. Preserve the working product while doing so.
2. Never delete or silently replace a working implementation until the new one
   is implemented, tested, run on the same fixtures, compared with the old one,
   and shown functionally equivalent or better.
3. Every functional block must have a clear responsibility, explicit input and
   output contracts, minimal dependencies, unit tests, integration tests, and
   regression tests where practical.
4. External projects must gradually become replaceable engines, adapters, or
   providers rather than remain the foundation of the application.
5. Do not degrade existing functionality for architectural cleanliness.
6. Do not perform unrelated refactoring inside a task for one module.
7. The default sequence is: explore → plan → improve → implement → verify →
   review.
8. During migration, run old and new implementations on identical fixtures and
   compare outputs, including evidence, limitations, and failure behavior.
9. Missing data must remain distinct from a negative result: unavailable,
   skipped, and inconclusive are not score `0`.
10. Never silently delete functionality, public fields, evidence, limitations,
    or compatibility paths.
11. New architecture must allow individual engines to be replaced without
    changing the rest of the product.
12. Serious changes belong in a dedicated Handoff task branch/worktree. Keep the
    shared base branch clean and make the final merge a deliberate human action.
13. Infrastructure tasks may change AI Factory, Handoff, Git, runtime, workflow,
    setup, and ignore configuration; they must not change product business logic.
14. Before completion, inspect the diff and confirm that no unrelated product
    code was changed.
