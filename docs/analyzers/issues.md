# Issues analyzer

- ID: `repo-health.issues`
- Input: normalized SourceCraft Issues facts with per-component availability.
- Output: `CategoryResult` with lifecycle findings, bounded evidence,
  coverage/confidence and partial-component limitations.
- Policy: `issues-calibration-v2` / `issues-sourcecraft-policy-v1` in
  `config/analyzers/issues.yaml`.
- External engine: SourceCraft Issues collector only; CollectOSS compatibility
  remains behind the legacy health edge during migration.

Missing response, close-time, backlog or responsiveness components are
explicitly unavailable. Missing data never becomes a zero score or an invented
finding.

Checks: `uv run python scripts/verify_issues_fixture.py` and the issues unit/
integration tests.
