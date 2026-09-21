# Development

Install the target backend with `uv sync --extra dev`. The supported checks are:

```powershell
uv run pytest -q tests/unit/repo_health tests/contract/repo_health tests/adapter/repo_health tests/integration/repo_health tests/golden/repo_health tests/e2e
uv run ruff check src scripts tests
uv run mypy src/repo_health
uv run python scripts/verify_contracts.py --all
uv run python scripts/verify_parity.py
```

Keep analyzer logic behind `AnalyzerInput` and `CategoryResult`. Add behavior
changes to a golden or contract test first. Do not import API, persistence or
another analyzer from a category package. Use redacted scalar facts and stable
digests; wall-clock timestamps must not affect deterministic result payloads.
