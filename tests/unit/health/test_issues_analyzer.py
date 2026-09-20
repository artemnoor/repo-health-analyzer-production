"""Pure Issues metric, scoring, evidence, and status tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
)

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.health.integrations.issues_analyzer import (  # noqa: E402
    ISSUES_ANALYZER_ID,
    IssuesAnalyzer,
    analyze_issue_facts,
    percentile,
)
from repowise.core.analysis.health.integrations.issues_facts import (  # noqa: E402
    IssueMetricStatus,
    load_issues_policy,
    normalize_issue_inventory,
)

ROOT = Path(__file__).resolve().parents[3]
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


def _fixture() -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / "issues" / "rich.json").read_text(encoding="utf-8"))


def _metric(result, name: str):
    return next(metric for metric in result.metrics if metric.name == name)


def _base_result(*, status: AnalyzerStatus = AnalyzerStatus.INCONCLUSIVE, score: float | None = None) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=ISSUES_ANALYZER_ID,
        analyzer_version="legacy",
        status=status,
        score=score,
        score_dimension="delivery" if score is not None else None,
        metrics=(),
        available_weight=1.0 if score is not None else 0.0,
        total_weight=1.0 if score is not None else 0.0,
    )


def test_percentile_is_deterministic_linear_interpolation() -> None:
    assert percentile([], 0.5) is None
    assert percentile([10], 0.75) == 10
    assert percentile([1, 2], 0.75) == 1.75
    assert percentile([1, 2, 3, 4], 0.5) == 2.5


def test_rich_metrics_filter_bots_and_measure_reopen_backlog_and_percentiles() -> None:
    context = _context(_fixture())
    facts = normalize_issue_inventory(context, load_issues_policy(ROOT))
    analysis = analyze_issue_facts(context, facts, load_issues_policy(ROOT))

    assert facts.status is IssueMetricStatus.MEASURED
    assert _metric(analysis, "issues:open_issues").value == 2
    assert _metric(analysis, "issues:closed_issues").value == 4
    assert _metric(analysis, "issues:closure_ratio").value == pytest.approx(4 / 5)
    assert _metric(analysis, "issues:first_human_response_count").value == 4
    assert _metric(analysis, "issues:unanswered_issues").value == 2
    assert _metric(analysis, "issues:first_response_median_hours").value == pytest.approx(14.0)
    assert _metric(analysis, "issues:first_response_p75_hours").value == pytest.approx(43.0)
    assert _metric(analysis, "issues:time_to_close_median_hours").value == pytest.approx(288.0)
    assert _metric(analysis, "issues:time_to_close_p75_hours").value == pytest.approx(486.0)
    assert _metric(analysis, "issues:stale_open_issues").value == 1
    assert _metric(analysis, "issues:reopened_issues").value == 1
    assert _metric(analysis, "issues:comments_human").value == 4
    assert _metric(analysis, "issues:comments_bot").value == 2
    assert [(bucket["created"], bucket["closed"], bucket["net"]) for bucket in analysis.diagnostics["trend"]] == [(3, 2, 1), (2, 1, 1), (1, 1, 0)]
    assert analysis.score is not None
    assert set(analysis.eligible_components) == {"responsiveness", "resolution", "backlog_health", "maintenance_trend"}
    assert any("stale" in finding.id for finding in analysis.findings)
    assert any("unanswered" in finding.id for finding in analysis.findings)
    assert all("comment" not in ref.json_pointer.lower() for ref in analysis.evidence)


def test_one_issue_has_metrics_but_no_strong_score() -> None:
    inventory = {
        "records_available": True,
        "pagination_complete": True,
        "local_date_filter_applied": True,
        "comments_available": True,
        "state_events_available": True,
        "issues": [
            {
                "id": "single",
                "created_at": "2026-09-01T00:00:00Z",
                "state": "open",
                "author": {"login": "reporter", "is_bot": False},
                "events": [{"id": "single-open", "type": "opened", "created_at": "2026-09-01T00:00:00Z", "is_state_transition": True}],
            }
        ],
    }
    context = _context(inventory)
    facts = normalize_issue_inventory(context, load_issues_policy(ROOT))
    analysis = analyze_issue_facts(context, facts, load_issues_policy(ROOT))

    assert _metric(analysis, "issues:sample_size").value == 1
    assert analysis.score is None
    assert "responsiveness" not in analysis.eligible_components


def test_closed_at_field_overrides_synthetic_opened_event() -> None:
    inventory = {
        "records_available": True,
        "records_expected": 1,
        "pagination_complete": True,
        "local_date_filter_applied": True,
        "comments_available": True,
        "state_events_available": False,
        "issues": [
            {
                "id": "closed-from-field",
                "created_at": "2026-07-01T00:00:00Z",
                "updated_at": "2026-07-04T00:00:00Z",
                "closed_at": "2026-07-04T00:00:00Z",
                # This deliberately mirrors a stale/current-state mismatch
                # seen in the live SourceCraft normalization probe.
                "state": "open",
                "author": {"login": "reporter", "is_bot": False},
            }
        ],
        "issue_comments": [],
    }
    context = _context(inventory)
    facts = normalize_issue_inventory(context, load_issues_policy(ROOT))
    analysis = analyze_issue_facts(context, facts, load_issues_policy(ROOT))

    assert _metric(analysis, "issues:open_issues").value == 0
    assert _metric(analysis, "issues:closed_issues").value == 1
    assert _metric(analysis, "issues:closure_ratio").value == pytest.approx(1.0)


def test_missing_state_events_makes_reopen_metric_unavailable_not_zero() -> None:
    inventory = _fixture()
    inventory["state_events_available"] = False
    context = _context(inventory)
    facts = normalize_issue_inventory(context, load_issues_policy(ROOT))
    analysis = analyze_issue_facts(context, facts, load_issues_policy(ROOT))

    assert _metric(analysis, "issues:reopened_issues").value is None
    assert analysis.diagnostics["metric_statuses"]["reopened"] == "NOT_APPLICABLE"


def test_missing_comments_suppresses_responsiveness_without_turning_it_into_zero_data() -> None:
    inventory = _fixture()
    inventory["comments_available"] = False
    context = _context(inventory)
    facts = normalize_issue_inventory(context, load_issues_policy(ROOT))
    analysis = analyze_issue_facts(context, facts, load_issues_policy(ROOT))

    assert analysis.diagnostics["metric_statuses"]["responsiveness"] == "UNAVAILABLE"
    assert "responsiveness" not in analysis.eligible_components
    assert "backlog_health" not in analysis.eligible_components
    assert _metric(analysis, "issues:first_human_response_count").value is None
    assert _metric(analysis, "issues:unanswered_issues").value is None
    assert _metric(analysis, "issues:unanswered_ratio").value is None
    assert _metric(analysis, "issues:first_response_median_hours").value is None
    assert not any("unanswered" in finding.id or "stale" in finding.id for finding in analysis.findings)
    assert any("comments" in limitation.reason.lower() for limitation in analysis.limitations)


def test_analyzer_outputs_are_stable_except_for_runtime_duration() -> None:
    context = _context(_fixture())
    base = _base_result()
    first = IssuesAnalyzer().analyze(context, base)
    second = IssuesAnalyzer().analyze(context, base)

    assert first.score == second.score
    assert [metric.model_dump() for metric in first.metrics] == [metric.model_dump() for metric in second.metrics]
    assert [finding.model_dump() for finding in first.findings] == [finding.model_dump() for finding in second.findings]
    assert [ref.model_dump() for ref in first.evidence] == [ref.model_dump() for ref in second.evidence]
    assert first.diagnostics["issues"] == second.diagnostics["issues"]


def test_analyzer_preserves_legacy_result_when_granular_source_is_missing() -> None:
    context = _context({"chaoss_rows": {"pull_requests_new": [{"value": 2}]}})
    base = AnalyzerResult(
        analyzer_id=ISSUES_ANALYZER_ID,
        analyzer_version="legacy",
        status=AnalyzerStatus.PASS,
        score=61.0,
        score_dimension="delivery",
        available_weight=1.0,
        total_weight=1.0,
    )

    result = IssuesAnalyzer().analyze(context, base)

    assert result.status is AnalyzerStatus.PASS
    assert result.score == 61.0
    assert result.diagnostics["issues_status"] == "UNAVAILABLE"
    assert result.analyzer_version == "issues-sourcecraft-policy-v1"


def test_analyzer_uses_aggregate_score_once_and_keeps_component_scores_empty() -> None:
    context = _context(_fixture())
    base = _base_result(score=80.0)

    result = IssuesAnalyzer().analyze(context, base)

    assert result.score is not None
    assert result.score != 80.0
    assert result.score_dimension == "delivery"
    assert all(metric.score is None for metric in result.metrics)
    assert result.diagnostics["issues_score"]["applied_share"] == pytest.approx(0.25)
    assert result.diagnostics["issues"]["double_count_guard"].startswith("one_aggregate")
