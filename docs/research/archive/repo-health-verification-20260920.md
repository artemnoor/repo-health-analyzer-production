# Repo Health verification record

Date: 2026-09-20

## Passed

- Repo Health contract/adapter/integration/parity/score selection: **134
  passed**.
- Frozen score v1 live verifier: completed with `raw_payloads_written=false`
  and `token_logged=false`; expected unavailable-tool limitations remained
  visible.
- `scripts/verify_health_completion.py`.
- `scripts/verify_health_docs.py`.
- `scripts/verify_worker_package.py`.
- `scripts/verify_source_update.py`.
- `scripts/verify_repo_health_cleanup.py`.
- `scripts/vendor_sources.py --verify` with all 21 ledger entries passing,
  including the pinned `vendor/collectoss` tree at commit
  `339edc520e79dd1728ca19255d94a05a4a107df1`.
- Worker readiness with the memory queue.
- Clean wheel build and artifact allowlist: `repowise-0.49.0-py3-none-any.whl`.
- The two legacy CLI worktree auto-seed tests after fixing UTF-8 decoding of
  Git paths on Windows.
- Complete `tests/integration/test_cli.py`: **47 passed**, 59 warnings.

## Open gates

- Host-wide `pytest` initially collected a nested sample-repository test; the
  test-discovery boundary now excludes `tests/fixtures`. The complete suite
  was started and intentionally stopped at 19% after exposing unrelated
  RepoWise baseline failures in `test_kg_skip_logic`, agent matrix/target
  tests, plugin content tests, and hook/mascot/provider tests. Those failures
  are outside this Repo Health cleanup; the complete CLI integration suite
  and the Repo Health verification matrix are green.

The prior CollectOSS drift was line-ending materialization on Windows, not a
different source revision. The old copy remains recoverable at
`%TEMP%\\repo-health-cleanup-quarantine-20260920\\vendor-collectoss-before-pinned-20260921`;
the working tree now contains the exact pinned source tree. The worktree
auto-seed failures had the same root cause: Git paths containing Cyrillic
characters were decoded with the platform default encoding. The fix is
localized to the shared Git output helper and preserves the existing seed
algorithm.
