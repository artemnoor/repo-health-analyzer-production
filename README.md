# SourceCraft Repository Health Analyzer

Backend-only service that collects SourceCraft and Git facts, runs six isolated
repository analyzers, calculates the frozen Repo Health Score v1, and exposes
versioned results through REST and background workers.

## Pipeline

```text
SourceCraft/Git → normalized RepositoryFacts → six analyzers
→ CategoryResult[] → ScoreEngineV1 → SQLite result envelope → REST API
```

The six categories are Documentation, Activity, Issues, CI/CD, Security and
Code Health. Missing or unavailable data remains explicit through status,
coverage, confidence and limitations; it is never silently converted to zero.

## Run locally

Requirements: Python 3.11+, `uv` and Git. Node.js is not required.

```powershell
uv sync --extra dev
uv run repo-health-api
```

The API listens on `http://127.0.0.1:8000` by default. Check it with:

```powershell
curl.exe http://127.0.0.1:8000/healthz
curl.exe http://127.0.0.1:8000/readyz
```

Set `SOURCECRAFT_URL` and `SOURCECRAFT_TOKEN` for live SourceCraft collection.
Set `VALE_PATH`, `GIT_SIZER_PATH`, `SONAR_URL` and `SONAR_TOKEN` only when those
optional engines are available. Missing engines degrade only their category;
they never become fabricated zero facts. Tokens are resolved at execution time
and are not stored in contracts, task rows, logs or responses. See
[.env.example](.env.example).

## Verify

```powershell
uv run pytest -q tests/unit/repo_health tests/contract/repo_health tests/adapter/repo_health tests/integration/repo_health tests/golden/repo_health tests/e2e
uv run python scripts/verify_contracts.py --all
uv run python scripts/verify_parity.py
uv run python -m repo_health.worker --check
uv run python scripts/verify_external_tools.py
uv run python scripts/verify_production_composition.py
```

## Documentation

- [Architecture](docs/architecture.md)
- [Scoring](docs/scoring.md)
- [Analyzers](docs/analyzers.md)
- [SourceCraft integration](docs/sourcecraft.md)
- [REST API](docs/api.md)
- [Development](docs/development.md)
- [Deployment](docs/deployment.md)

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
