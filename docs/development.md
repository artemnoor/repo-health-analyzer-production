# Development

Install the target backend with `uv sync --extra dev`. The supported checks are:

```powershell
uv run pytest -q tests/unit/repo_health tests/contract/repo_health tests/adapter/repo_health tests/integration/repo_health tests/golden/repo_health tests/e2e
uv run ruff check src scripts tests
uv run python -m compileall -q src scripts tests
uv run python scripts/verify_contracts.py --all
uv run python scripts/verify_parity.py --score-only
uv run python scripts/verify_parity.py --legacy-replay --fail-on-unmapped
uv run python scripts/verify_parity.py --execution local --execution worker
uv run python scripts/verify_external_tools.py
uv run python scripts/verify_production_composition.py
```

`repo_health.runtime.build_production_runtime` is the only production
composition root. API, worker and scheduler use it; tests may override the
explicit `create_app` dependencies for deterministic fixtures. Capability
states (`available`, `unavailable`, `misconfigured`) are detected from typed
environment configuration without logging credential values.

Use `uv run python scripts/verify_production_composition.py --live` only when
the checkout path and real SourceCraft/SonarQube credentials are configured.
The command prints one safe row per category with source, adapter, status,
score, coverage, confidence and evidence count.

Keep analyzer logic behind `AnalyzerInput` and `CategoryResult`. Add behavior
changes to a golden or contract test first. Do not import API, persistence or
another analyzer from a category package. Use redacted scalar facts and stable
digests; wall-clock timestamps must not affect deterministic result payloads.
