.PHONY: install test lint typecheck verify api worker build docker

install:
	uv sync --extra dev

test:
	uv run pytest -q tests/unit/repo_health tests/contract/repo_health tests/adapter/repo_health tests/integration/repo_health tests/golden/repo_health tests/e2e

lint:
	uv run ruff check src scripts tests

typecheck:
	uv run mypy src/repo_health

verify:
	$(MAKE) lint
	$(MAKE) test
	uv run python scripts/verify_contracts.py --all
	uv run python scripts/verify_parity.py

api:
	uv run repo-health-api

worker:
	uv run repo-health-worker --once

build:
	uv build

docker:
	docker build -t repo-health-analyzer:local .
