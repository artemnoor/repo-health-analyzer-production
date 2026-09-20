"""End-to-end CI/CD analyzer tests over the registered health boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.unit.health.issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.analyzer_integration.contracts import (  # noqa: E402
    AnalyzerContext,
    AnalyzerStatus,
)
from repowise.core.analysis.health.integrations import (  # noqa: E402
    register_all_health_adapters,
)
from repowise.core.analysis.health.integrations.registry import (  # noqa: E402
    AnalyzerRegistry,
)

ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime(2026, 9, 19, tzinfo=UTC)


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=ROOT,
        repo_id="integration/cicd",
        head_sha="integration-head",
        as_of_ts=AS_OF,
        mode="offline",
        inventory={"sourcecraft_cicd": inventory},
    )


def _fixture(name: str) -> dict:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "cicd" / f"{name}.json").read_text(
            encoding="utf-8"
        )
    )


def test_registered_cicd_path_normalizes_sourcecraft_inventory_and_returns_delivery_result() -> None:
    registry = AnalyzerRegistry()
    register_all_health_adapters(registry)
    context = _context(_fixture("failure_streak"))
    planned = next(
        item for item in registry.plan(context) if item.definition.id == "cicd.sourcecraft"
    )

    result = registry.run(planned, context)

    assert result.status is AnalyzerStatus.FAIL
    assert result.analyzer_id == "cicd.sourcecraft"
    assert result.score_dimension == "delivery"
    assert result.diagnostics["cicd_status"] == "MEASURED"
    assert result.diagnostics["cicd"]["total_runs"] == 6
    assert result.metrics
    assert result.evidence[0].source == "sourcecraft"
    assert all("log" not in str(item.model_dump()).lower() for item in result.evidence)


def test_registered_cicd_path_keeps_source_errors_visible_without_zero_score() -> None:
    registry = AnalyzerRegistry()
    register_all_health_adapters(registry)
    context = _context(_fixture("unavailable"))
    planned = next(
        item for item in registry.plan(context) if item.definition.id == "cicd.sourcecraft"
    )

    result = registry.run(planned, context)

    assert result.status is AnalyzerStatus.SKIPPED
    assert result.score is None
    assert result.diagnostics["cicd_status"] == "UNAVAILABLE"
