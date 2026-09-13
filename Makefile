.PHONY: install install-dev test test-unit test-integration test-e2e test-providers \
        generate-types generate-types-check \
        lint format typecheck clean build-web dev-web help \
        vendor-verify build-native test-python test-native test-composition \
        health-sample health-replay health-clean health-contract health-completion docs-check

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:  ## Install all Python packages in the workspace
	uv sync --all-packages

install-dev:  ## Install all packages including dev dependencies
	uv sync --all-packages --all-extras

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test:  ## Run all tests
	uv run pytest tests/ -v

test-unit:  ## Run unit tests only
	uv run pytest tests/unit/ -v

test-integration:  ## Run integration tests only
	uv run pytest tests/integration/ -v

test-e2e:  ## Run end-to-end tests only
	uv run pytest tests/e2e/ -v

test-providers:  ## Run provider tests only (no API keys required)
	uv run pytest tests/providers/ -v

test-fast:  ## Run unit + provider tests (fast, no fixtures needed)
	uv run pytest tests/unit/ tests/providers/ -v -q

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

generate-types:  ## Regenerate the TypeScript HTTP contract from the FastAPI schema
	uv run python scripts/generate_http_types.py

generate-types-check:  ## Fail if the generated HTTP contract is stale
	uv run python scripts/generate_http_types.py --check

lint:  ## Run ruff linter
	uv run ruff check packages/ tests/

format:  ## Run ruff formatter
	uv run ruff format packages/ tests/

format-check:  ## Check formatting without modifying files
	uv run ruff format --check packages/ tests/

typecheck:  ## Run mypy type checker
	uv run mypy packages/core/src packages/cli/src packages/server/src

check: lint format-check typecheck  ## Run all checks (no modifications)

fix: format lint  ## Format + lint with auto-fix

# ---------------------------------------------------------------------------
# Code Health (Phase 4)
# ---------------------------------------------------------------------------

vendor-verify:  ## Verify every copied source tree against vendor/SOURCES.lock
	uv run python scripts/vendor_sources.py --verify

docs-check:  ## Verify documented paths, source commits, CI jobs and commands
	uv run python scripts/verify_health_docs.py

build-native:  ## Build required Go health tools; report optional toolchain skips
	uv run python scripts/build_native_health.py

test-python:  ## Run health contracts, adapters, persistence and projections
	uv run ruff check scripts/vendor_sources.py scripts/verify_health_stack.py scripts/build_native_health.py scripts/test_native_health.py scripts/health_clean.py scripts/check_health_gate.py scripts/verify_health_docs.py
	DATABASE_URL= uv run pytest tests/unit/health tests/unit/persistence tests/unit/server/test_health_canonical.py tests/unit/server/mcp/test_health_canonical_projection.py tests/unit/cli/test_health_persist_analyzed_commit.py -q

test-native:  ## Run copied native suites and explicit platform skip policy
	uv run python scripts/test_native_health.py

test-composition:  ## Run the full redacted health composition gate
	uv run python scripts/verify_health_stack.py --full

health-sample:  ## Write a deterministic sample report from the replay fixture
	mkdir -p artifacts
	uv run repowise health tests/fixtures/health/replay_repo --no-workspace --format json --health-mode full --as-of 2026-01-01T00:00:00Z > artifacts/health-sample.json
	@echo "Health sample -> artifacts/health-sample.json"

health-replay:  ## Replay and compare the pinned health fixture
	uv run python scripts/verify_health_stack.py --full

health-clean:  ## Remove only generated health report files
	uv run python scripts/health_clean.py

health-contract:  ## Run the focused canonical score/ranking contract gate
	uv run python scripts/verify_health_completion.py --run-tests

health-completion: health-contract  ## Verify the complete repository-health source surface

health-check:  ## Run the code-health analyzer against this repo and fail on regressions
	uv run pytest tests/unit/health/ tests/unit/server/test_mcp.py -v
	uv run repowise health --format json > /tmp/repowise-health-report.json || true
	@echo "Health report → /tmp/repowise-health-report.json"

health-bench:  ## Run the 3,000-file health analyzer perf benchmark
	uv run pytest tests/integration/test_health_perf_benchmark.py -v -m slow

# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

dev-web:  ## Start Next.js dev server
	cd packages/web && npm run dev

build-web:  ## Build Next.js production output
	cd packages/web && npm run build

install-web:  ## Install Node dependencies for web package
	cd packages/web && npm install

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

clean:  ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

build:  ## Build all Python distributions
	uv build --all-packages

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
