# CI/CD analyzer

- ID: `repo-health.cicd`
- Input: normalized SourceCraft CI runs and capability facts.
- Output: `CategoryResult` with terminal/decisive-run evidence, failure streak,
  duration/trend metrics, coverage/confidence and DORA limitations.
- Policy: `cicd-calibration-v2` / `cicd-sourcecraft-policy-v1` in
  `config/analyzers/cicd.yaml`.
- External engine: SourceCraft CI collector only.

Pagination, terminal status selection, missing CI configuration and provider
permissions retain their explicit status semantics. The calibration-v2 score
and policy digest are frozen.

Checks: `uv run python scripts/verify_cicd_fixture.py` and the CI/CD tests.
