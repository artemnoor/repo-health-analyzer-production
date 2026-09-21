# Contributing

This repository contains the backend-only SourceCraft Repository Health
Analyzer.

## Local setup

Requirements: Python 3.11+, Git and `uv`.

```text
uv sync --extra dev
uv run ruff check src scripts tests
uv run pytest -q tests/unit/repo_health tests/contract/repo_health tests/adapter/repo_health tests/integration/repo_health tests/golden/repo_health tests/e2e
uv build
```

Keep changes inside the contract-first boundaries described in
[`docs/architecture.md`](../docs/architecture.md). Do not change Score v1 or
calibration-v2 semantics without updating the golden parity tests and recording
the compatibility decision.
