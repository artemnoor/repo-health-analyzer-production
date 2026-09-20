"""Metric, score, status, evidence, and DORA tests for CI/CD analysis."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.analyzer_integration.contracts import (  # noqa: E402
    AnalyzerContext,
    AnalyzerStatus,
)
from repowise.core.analysis.health.integrations.cicd_analyzer import (  # noqa: E402
    CICDAnalyzer,
)
from repowise.core.analysis.health.integrations.cicd_facts import (  # noqa: E402
    CICDDataStatus,
)

ROOT = Path(__file__).resolve().parents[3]
AS_OF = datetime(2026, 9, 19, tzinfo=UTC)


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _fixture(name: str) -> dict:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "cicd" / f"{name}.json").read_text(
            encoding="utf-8"
        )
    )


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=ROOT,
        repo_id="fixture/cicd",
        head_sha="fixture-head",
        as_of_ts=AS_OF,
        mode="offline",
        inventory={"sourcecraft_cicd": inventory},
    )


def _result(name: str):
    return CICDAnalyzer().run(_context(_fixture(name)))


def _metric(result, name: str):
    return next(metric for metric in result.metrics if metric.name == name)


def test_all_success_is_measured_with_bounded_score_and_no_component_scores() -> None:
    result = _result("all_success")

    assert result.status is AnalyzerStatus.PASS
    assert result.score is not None
    assert 0 < result.score <= 100
    assert _metric(result, "cicd:success_rate").value == 1.0
    assert _metric(result, "cicd:failure_rate").value == 0.0
    assert all(metric.score is None for metric in result.metrics)
    assert result.available_weight == result.total_weight == 1.0
    assert result.score_dimension == "delivery"


def test_failure_streak_is_a_measured_negative_and_can_fail_status() -> None:
    result = _result("failure_streak")

    assert result.status is AnalyzerStatus.FAIL
    assert result.score is not None
    assert _metric(result, "cicd:consecutive_failure_streak").value == 5
    assert any(finding.subject == "failure-streak" for finding in result.findings)
    assert any(finding.subject == "failure-rate" for finding in result.findings)
    assert result.diagnostics["problem_runs"]
    assert all(item["run_id"] for item in result.diagnostics["problem_runs"])
    failure_finding = next(finding for finding in result.findings if finding.subject == "failure-rate")
    assert len(failure_finding.evidence_refs) == 5


def test_no_ci_and_no_runs_do_not_produce_zero_score() -> None:
    no_ci = _result("no_ci")
    no_runs = _result("configured_no_runs")

    assert no_ci.status is AnalyzerStatus.SKIPPED
    assert no_ci.score is None
    assert no_ci.diagnostics["cicd_status"] == CICDDataStatus.CI_NOT_CONFIGURED.value
    assert no_runs.status is AnalyzerStatus.INCONCLUSIVE
    assert no_runs.score is None
    assert no_runs.diagnostics["cicd_status"] == CICDDataStatus.NO_RUNS.value


def test_unavailable_source_is_skipped_not_failure() -> None:
    result = _result("unavailable")

    assert result.status is AnalyzerStatus.SKIPPED
    assert result.score is None
    assert result.diagnostics["cicd_status"] == CICDDataStatus.UNAVAILABLE.value
    assert any(limit.kind == "missing_capability" for limit in result.limitations)


def test_mixed_statuses_do_not_treat_cancelled_skipped_or_rejected_as_failure() -> None:
    result = _result("mixed_statuses")

    assert _metric(result, "cicd:cancelled_runs").value == 1
    assert _metric(result, "cicd:skipped_runs").value == 1
    assert _metric(result, "cicd:rejected_runs").value == 1
    assert _metric(result, "cicd:failure_runs").value == 2
    assert _metric(result, "cicd:failure_rate").value == pytest.approx(2 / 3)
    assert _metric(result, "cicd:consecutive_failure_streak").value == 1
    assert result.score is None


def test_retry_success_is_reported_as_proven_flaky_signal() -> None:
    result = _result("retry_flaky")

    assert _metric(result, "cicd:flaky_failure_to_success_count").value == 1
    assert any(finding.subject == "proven-flaky-run" for finding in result.findings)
    assert result.diagnostics["cicd"]["retry_detection_status"] == "MEASURED"


def test_duration_p50_p95_and_trend_are_deterministic() -> None:
    first = _result("duration_trend")
    second = _result("duration_trend")

    assert _metric(first, "cicd:current:duration_p50_seconds").value == 800
    assert _metric(first, "cicd:current:duration_p95_seconds").value == pytest.approx(980)
    assert _metric(first, "cicd:previous:duration_p50_seconds").value == 120
    assert _metric(first, "cicd:stability_trend").value == "worsening"
    assert first.diagnostics["component_scores"] == second.diagnostics["component_scores"]
    assert [item.model_dump() for item in first.metrics] == [
        item.model_dump() for item in second.metrics
    ]


def test_partial_history_warns_and_adjusts_confidence() -> None:
    result = _result("partial_pagination")

    assert result.status is AnalyzerStatus.WARN
    assert result.score is not None
    assert result.diagnostics["cicd_status"] == CICDDataStatus.PARTIAL.value
    assert result.diagnostics["cicd"]["coverage"] < 1.0
    assert any(limit.kind == "insufficient_denominator" for limit in result.limitations)


def test_dora_metrics_are_status_only_when_capabilities_are_absent() -> None:
    result = _result("all_success")

    for name in (
        "deployment_frequency",
        "lead_time_for_changes",
        "change_failure_rate",
        "time_to_restore",
    ):
        assert _metric(result, f"dora:{name}:status").value == "NOT_APPLICABLE"
    assert all("DORA" in limitation.reason for limitation in result.limitations)


def test_single_run_is_visible_but_cannot_score() -> None:
    payload = _fixture("all_success")
    payload["runs"] = [payload["runs"][0]]
    result = _result_from_payload(payload)

    assert result.status is AnalyzerStatus.INCONCLUSIVE
    assert result.score is None
    assert _metric(result, "cicd:total_runs").value == 1


def test_analyzer_policy_failure_is_explicit_error() -> None:
    analyzer = CICDAnalyzer(policy_loader=lambda: (_ for _ in ()).throw(ValueError("bad policy")))
    result = analyzer.run(_context(_fixture("all_success")))

    assert result.status is AnalyzerStatus.ERROR
    assert result.score is None
    assert result.diagnostics["cicd_status"] == CICDDataStatus.ERROR.value


def _result_from_payload(payload: dict):
    return CICDAnalyzer().run(_context(payload))
