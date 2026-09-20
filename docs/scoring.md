# Repo Health Score v1

Score v1 is frozen. Migration work must preserve weights, coverage/confidence
semantics, `K`, security caps, calibration-v2 policies, evidence and
limitations. The canonical implementation is
`health/score_engine_v1.py`, exposed through the `FrozenRepoHealthScorePort`.

Weights are Documentation 0.15, Activity 0.15, Issues 0.15, CI/CD 0.15,
Security 0.20 and Code Health 0.20. For category quality
`q_j = coverage_j * confidence_j`, and
`K = sum(w_j * q_j) / sum(w_j)`. A normal score requires at least five numeric
categories and `K >= 0.75`; provisional publication requires at least four and
`K >= 0.50`. Missing data remains unavailable, never an invented zero.

The security caps remain `confirmed_high=60`, `confirmed_critical=40` and
`confirmed_secret=40`. Every result carries policy/config digests, category
status, coverage, confidence, evidence coverage and visible limitations.

Source of truth:

- `config/analyzers/repo-health-score-v1.yaml`;
- `packages/core/src/repowise/core/analysis/health/score_engine_v1.py`;
- calibration-v2 policy files and golden tests under `tests/unit/health`;
- archived behavior/parity ledger under `docs/research/archive/`.

Verify with:

```text
uv run pytest -q tests/unit/health/test_repo_health_score_v1.py tests/unit/health/test_score_invariants.py tests/unit/health/test_analyzer_integration_parity.py
uv run python scripts/verify_repo_health_score_v1.py
```
