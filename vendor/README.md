# Vendored analyzer sources

This directory contains whole-tree or package-tree snapshots copied from pinned
upstream commits for the Repository Health Analyzer. The source snapshots remain
in their native language, package layout, tests and build system. Integration
code must call them through the canonical analyzer contract; it must not copy
their algorithms into `packages/core`.

The authoritative source and build ledger is [`SOURCES.lock`](SOURCES.lock).
Each executable source has a corresponding local Git metadata root under
`.sources/` and a pinned commit. `reference-only` entries describe product
references for which no source tree is copied. The ledger's `verify_mode` is
also authoritative: `git-tree` checks every copied blob, while `sentinels`
checks the pinned commit plus the explicitly required files for a partial or
platform-specific vendor snapshot.

Rules:

- Preserve upstream `LICENSE*`, `NOTICE*`, `README*`, manifests and tests.
- Treat copied source files as upstream-owned. Put local glue in the paths named
  by the implementation plan and record intentional overlays in the adapter.
- Build outputs belong in `bin/` or native tool build directories, never in a
  copied source tree.
- Update a source only with an explicit commit SHA, a ledger diff, source-tree
  verification and the upstream test command recorded in the ledger.
- Run `python scripts/vendor_sources.py --verify` before changing adapters.
