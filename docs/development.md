# Development

Install the workspace with Python 3.11+, `uv`, Git and Node.js when working
on the web package:

```text
uv sync --all-packages --all-extras
```

The contract-first checks are the fastest gate:

```text
uv run ruff check packages/core/src/repowise/core/repo_health scripts/verify_repo_health_cleanup.py
uv run pytest -q tests/contract/repo_health tests/unit/repo_health
uv run pytest -q tests/integration/repo_health
uv run python scripts/verify_worker_package.py
uv run python scripts/verify_repo_health_cleanup.py
```

Use fixture replay for analyzer work. Live SourceCraft, SonarQube and Vale
checks are opt-in and must write only redacted evidence under local ignored
run directories. Do not copy an external repository into `packages/` or the
worker package; use an adapter/process boundary and record provenance in the
legal matrix.

Before changing a score or analyzer policy, run the relevant golden/parity
tests and compare the archived behavior baseline. Do not change v1 weights,
`K`, security caps or calibration-v2 formulas as part of structural cleanup.

The durable workflow is explore → plan → improve → implement → verify →
review. Keep broader RepoWise jobs on their existing executor while Repo
Health tasks use their own queue namespace.
