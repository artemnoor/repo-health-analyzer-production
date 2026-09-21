# SourceCraft Repository Health Analyzer implementation

Status: backend extraction and radical cleanup implemented; final verification
gates passed from a clean Git index archive.

The historical implementation plan is preserved as local AI Factory session
state and is intentionally excluded from the production archive. The tracked
architecture and rules files are the durable project contract; verification
commands below are the durable execution surface.

## Product boundary

`SourceCraft/Git collection → normalized RepositoryFacts → six isolated
analyzers → CategoryResult[] → frozen Score v1 → SQLite persistence → REST API
and scheduler/worker execution`.

The repository no longer ships a frontend, Node workspace, editor integration,
MCP/agent product, copied upstream repositories, spike corpus, or unrelated
server routes. The runtime is the standalone `src/repo_health` package.

## Protected behavior

- Documentation, Activity, Issues, CI/CD, Security, and Code Health calibration-v2
  semantics;
- Repo Health Score v1 weights, K thresholds, security caps, ordering and digest;
- evidence, coverage, confidence, partial/unavailable states and SourceCraft
  adapter redaction;
- local/worker serialized contract parity and golden fixtures.

## Verification commands

```text
uv sync --frozen --extra dev
uv run ruff check src scripts tests
uv run pytest -q tests/unit/repo_health tests/contract/repo_health tests/adapter/repo_health tests/integration/repo_health tests/golden/repo_health tests/e2e
uv run python scripts/verify_contracts.py --all
uv run python scripts/verify_parity.py --score-only
uv run python scripts/verify_parity.py --legacy-replay --fail-on-unmapped
uv run python scripts/verify_parity.py --execution local --execution worker
uv build
```

Legacy paths may only be restored from the recoverable pre-cleanup quarantine
outside the repository if a new parity defect is demonstrated.
