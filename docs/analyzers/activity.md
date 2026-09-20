# Activity analyzer

- ID: `repo-health.activity`
- Input: normalized Git/PyDriller facts; no PyDriller domain objects cross the
  boundary.
- Output: `CategoryResult` with activity evidence, bounded history metrics,
  coverage/confidence and calibration limitations.
- Policy: `activity-calibration-v2` and `config/analyzers/pydriller.yaml`.
- External engine: PyDriller as a pinned Python dependency plus local Git
  facts.

Empty history, duplicate commits and unavailable repository capabilities remain
visible. The existing activity formula and PyDriller share/overlap policy are
preserved.

Checks: `uv run python scripts/verify_pydriller_activity_fixture.py` and
`tests/unit/health/test_activity_analyzer_pydriller.py`.
