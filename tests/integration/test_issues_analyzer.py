"""Issues analyzer integration and legacy envelope regression tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerStatus,
)
from tests.unit.health.issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.analyzer_integration.cache import cache_key  # noqa: E402
from repowise.core.analysis.health.composite import compose_health_score  # noqa: E402
from repowise.core.analysis.health.integrations.chaoss_adapter import (  # noqa: E402
    CHAOSS_ISSUES_PRS_ID,
    DEFINITIONS,
    issues_prs_adapter,
)
from repowise.core.analysis.health.integrations.contracts import AnalyzerDefinition  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime(2026, 9, 10, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def _restore_coverage_shim():
    yield
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=ROOT,
        repo_id="fixture/issues",
        head_sha="fixture-head",
        as_of_ts=AS_OF,
        mode="offline",
        inventory=inventory,
        capabilities=("chaoss:events",),
    )


def _rich() -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / "issues" / "rich.json").read_text(encoding="utf-8"))


def test_registry_boundary_preserves_pr_metrics_and_adds_issue_facts() -> None:
    inventory = _rich()
    inventory["chaoss_rows"] = {"pull_requests_new": [{"value": 3, "id": "pr-aggregate"}]}

    result = issues_prs_adapter(_context(inventory))

    assert result.analyzer_id == CHAOSS_ISSUES_PRS_ID
    assert result.analyzer_version == DEFINITIONS[CHAOSS_ISSUES_PRS_ID].version
    assert any(metric.name == "chaoss:pull_requests_new" for metric in result.metrics)
    assert any(metric.name == "issues:open_issues" for metric in result.metrics)
    assert result.diagnostics["issues_status"] == "MEASURED"
    assert result.score_dimension == "delivery"


def test_pr_only_legacy_envelope_stays_usable_with_no_issue_score() -> None:
    inventory = {
        "issues": [],
        "records_available": True,
        "status": "NO_ISSUES",
        "pagination_complete": True,
        "local_date_filter_applied": True,
        "comments_available": True,
        "state_events_available": True,
        "chaoss_rows": {"pull_requests_new": [{"value": 2, "id": "pr-1"}]},
    }

    result = issues_prs_adapter(_context(inventory))

    assert result.status is AnalyzerStatus.PASS
    assert result.score is None
    assert result.diagnostics["issues_status"] == "NO_ISSUES"
    assert any(metric.name == "chaoss:pull_requests_new" for metric in result.metrics)


def test_missing_events_capability_is_skipped_by_runner_boundary_not_scored_zero() -> None:
    from repowise.core.analysis.health.integrations.registry import registry

    context = _context({"issues": []})
    context = context.model_copy(update={"capabilities": ()})
    planned = next(item for item in registry.plan(context) if item.definition.id == CHAOSS_ISSUES_PRS_ID)
    result = {CHAOSS_ISSUES_PRS_ID: registry.run(planned, context)}

    assert result[CHAOSS_ISSUES_PRS_ID].status is AnalyzerStatus.SKIPPED
    assert result[CHAOSS_ISSUES_PRS_ID].score is None


def test_global_composition_accepts_issues_aggregate_once() -> None:
    result = issues_prs_adapter(_context(_rich()))
    composed = compose_health_score((result,))

    assert composed.dimensions["delivery"] == pytest.approx(result.score)
    assert len([item for item in composed.breakdown if item["dimension"] == "delivery"]) == 1


def test_policy_version_is_part_of_cache_identity() -> None:
    context = _context(_rich())
    current = DEFINITIONS[CHAOSS_ISSUES_PRS_ID]
    legacy = AnalyzerDefinition.model_validate({**current.model_dump(), "version": "legacy"})

    assert cache_key(current, context) != cache_key(legacy, context)
