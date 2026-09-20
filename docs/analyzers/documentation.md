# Documentation analyzer

- ID: `repo-health.documentation`
- Input: `AnalyzerInput` / normalized documentation and repository facts.
- Output: `CategoryResult` with score, findings, Vale evidence, coverage,
  confidence and limitations.
- Policy: `documentation-calibration-v2` plus `config/analyzers/vale.yaml`.
- External engine: Vale through `ProcessPort`; no Vale source is vendored in
  the worker artifact.

Missing docs, unavailable Vale and bounded output are explicit status or
limitation values. They are not silently converted to a passing score.

Checks: `uv run python scripts/verify_vale_fixture.py` and the documentation
analyzer tests under `tests/unit/health`.
