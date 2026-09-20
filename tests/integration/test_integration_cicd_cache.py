"""Health-edge registration and cache safety tests for CI/CD."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.unit.health.issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext  # noqa: E402
from repowise.core.analysis.health.integrations import register_all_health_adapters  # noqa: E402
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime(2026, 9, 19, tzinfo=UTC)


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _fixture(name: str) -> dict:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "cicd" / f"{name}.json").read_text(
            encoding="utf-8"
        )
    )


def _context(inventory: dict, cache_dir: Path | None = None) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=ROOT,
        repo_id="integration/cicd",
        head_sha="integration-head",
        as_of_ts=AS_OF,
        mode="offline",
        inventory={"sourcecraft_cicd": inventory},
        cache_dir=cache_dir,
    )


def test_registry_has_one_idempotent_cicd_entry() -> None:
    health = AnalyzerRegistry()
    register_all_health_adapters(health)
    first = health.ids()
    register_all_health_adapters(health)

    assert "cicd.sourcecraft" in first
    assert health.ids() == first
    definition, factory = health.get("cicd.sourcecraft")
    assert definition.requires == ()
    assert definition.cache_policy.value == "none"
    assert factory.__module__.endswith("cicd_analyzer")


def test_missing_capability_reaches_adapter_for_precise_status() -> None:
    health = AnalyzerRegistry()
    register_all_health_adapters(health)
    context = _context({})
    planned = next(item for item in health.plan(context) if item.definition.id == "cicd.sourcecraft")

    assert planned.missing_capabilities == ()
    result = health.run(planned, context)

    assert result.status.value == "skipped"
    assert result.score is None
    assert result.diagnostics["cicd_status"] == "UNAVAILABLE"


def test_cache_is_disabled_until_snapshot_digest_is_available(tmp_path: Path) -> None:
    health = AnalyzerRegistry()
    register_all_health_adapters(health)
    planned = next(
        item
        for item in health.plan(_context(_fixture("all_success"), tmp_path))
        if item.definition.id == "cicd.sourcecraft"
    )
    first = health.run(planned, _context(_fixture("all_success"), tmp_path))
    second = health.run(planned, _context(_fixture("failure_streak"), tmp_path))

    assert planned.definition.cache_policy.value == "none"
    assert first.cache_hit is False
    assert second.cache_hit is False
    assert first.diagnostics["cicd_status"] != second.diagnostics["cicd_status"] or first.score != second.score
