"""Activity composition and bounded PyDriller score policy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    Limitation,
)
from repowise.core.analysis.health.integrations.activity_analyzer import (
    ACTIVITY_POLICY_VERSION,
    ActivityAnalyzer,
)
from repowise.core.analysis.health.integrations.pydriller_adapter import (
    ActivityBucket,
    ActivityWindow,
    FailureKind,
    GitActivityBaseline,
    PyDrillerExecutionStatus,
    PyDrillerFacts,
    load_pydriller_policy,
)


class StubAdapter:
    def __init__(self, facts: PyDrillerFacts) -> None:
        self.facts = facts

    def collect(self, _context: AnalyzerContext, **_kwargs: Any) -> PyDrillerFacts:
        return self.facts


def _context() -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path(".").resolve(),
        repo_id="activity-test",
        head_sha="a" * 40,
        as_of_ts=datetime(2026, 9, 18, tzinfo=UTC),
        inventory={},
    )


def _facts(
    *,
    status: PyDrillerExecutionStatus = PyDrillerExecutionStatus.MEASURED,
    unique_commits: int = 4,
    confidence: float = 1.0,
    shallow: bool = False,
    failure_kind: FailureKind | None = None,
) -> PyDrillerFacts:
    as_of = datetime(2026, 9, 18, tzinfo=UTC)
    latest = as_of - timedelta(days=1) if status is PyDrillerExecutionStatus.MEASURED else None
    earliest = as_of - timedelta(days=8) if status is PyDrillerExecutionStatus.MEASURED else None
    buckets = (
        ActivityBucket(
            start_at=as_of - timedelta(days=7),
            end_at=as_of,
            commit_count=unique_commits,
            meaningful_commit_count=max(0, unique_commits - 1),
            churn=20,
            author_count=2,
        ),
    ) if status is PyDrillerExecutionStatus.MEASURED else ()
    return PyDrillerFacts(
        execution_status=status,
        failure_kind=failure_kind,
        failure_reason="synthetic failure" if failure_kind else None,
        repository_head="a" * 40,
        resolved_refs=("main",) if status is not PyDrillerExecutionStatus.UNAVAILABLE else (),
        history_is_shallow=shallow,
        history_complete=not shallow and status is PyDrillerExecutionStatus.MEASURED,
        unique_commit_count=unique_commits,
        commit_occurrence_count=unique_commits,
        unique_author_count=2,
        unique_committer_count=2,
        earliest_activity_at=earliest,
        latest_activity_at=latest,
        buckets=buckets,
        windows=(
            ActivityWindow(
                days=7,
                commit_count=unique_commits,
                meaningful_commit_count=max(0, unique_commits - 1),
                author_count=2,
                additions=15,
                deletions=5,
                churn=20,
                merge_commit_count=0,
                empty_commit_count=0,
            ),
        ) if status is PyDrillerExecutionStatus.MEASURED else (),
        total_additions=15,
        total_deletions=5,
        total_churn=20,
        low_change_commit_count=1,
        meaningful_activity_ratio=(0.75 if unique_commits else None),
        coverage=confidence,
        confidence=confidence,
        baseline_source="sourcecraft.git" if status is PyDrillerExecutionStatus.MEASURED else None,
        overlap_status="measured" if status is PyDrillerExecutionStatus.MEASURED else "not_applicable",
        overlap_commit_count=unique_commits - 1 if unique_commits else None,
        new_commit_count=1 if unique_commits else None,
        diagnostics={
            "as_of_ts": as_of,
            "bucket_days": 7,
            "max_window_days": 365,
        },
    )


def _base(*, status: AnalyzerStatus = AnalyzerStatus.INCONCLUSIVE, score: float | None = None) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id="chaoss.activity",
        analyzer_version="pinned",
        status=status,
        score=score,
        score_dimension="history" if score is not None else None,
        available_weight=1 if score is not None else 0,
        total_weight=1 if score is not None else 0,
        limitations=(
            (Limitation(reason="No CollectOSS rows", kind="insufficient_denominator"),)
            if status is AnalyzerStatus.INCONCLUSIVE
            else ()
        ),
    )


def _analyzer(facts: PyDrillerFacts) -> ActivityAnalyzer:
    policy = load_pydriller_policy()
    return ActivityAnalyzer(
        pydriller_adapter=StubAdapter(facts),
        policy_loader=lambda: policy,
    )


def test_measured_facts_add_observations_and_one_quality_metric() -> None:
    result = _analyzer(_facts()).analyze(_context(), _base())

    assert result.status is AnalyzerStatus.PASS
    assert result.analyzer_version == ACTIVITY_POLICY_VERSION
    assert result.score is not None
    assert result.score_dimension == "history"
    assert {metric.name for metric in result.metrics} >= {
        "pydriller:unique_commits",
        "pydriller:commits_7d",
        "pydriller:churn",
        "pydriller:activity_quality",
    }
    quality = next(metric for metric in result.metrics if metric.name == "pydriller:activity_quality")
    assert quality.denominator == 1
    assert quality.score == result.score
    assert result.diagnostics["pydriller_status"] == "MEASURED"


def test_existing_activity_score_limits_pydriller_share() -> None:
    base = _base(status=AnalyzerStatus.PASS, score=80)
    result = _analyzer(_facts()).analyze(_context(), base)
    quality = result.diagnostics["pydriller_score"]["quality_score"]

    assert result.score == pytest.approx(80 * 0.75 + quality * 0.25)
    assert result.diagnostics["pydriller_score"]["applied_share"] == pytest.approx(0.25)
    quality_metric = next(metric for metric in result.metrics if metric.name == "pydriller:activity_quality")
    assert quality_metric.denominator == 1
    assert quality_metric.score is None


def test_no_activity_is_inconclusive_and_has_no_zero_score() -> None:
    result = _analyzer(_facts(status=PyDrillerExecutionStatus.NO_ACTIVITY, unique_commits=0)).analyze(
        _context(), _base()
    )

    assert result.status is AnalyzerStatus.INCONCLUSIVE
    assert result.score is None
    assert any(limit.kind == "insufficient_denominator" for limit in result.limitations)


def test_unavailable_source_is_skipped_without_lowering_existing_result() -> None:
    unavailable = _facts(
        status=PyDrillerExecutionStatus.UNAVAILABLE,
        unique_commits=0,
        failure_kind=FailureKind.MISSING_DEPENDENCY,
    )
    result = _analyzer(unavailable).analyze(_context(), _base())

    assert result.status is AnalyzerStatus.SKIPPED
    assert result.score is None
    assert any(limit.kind == "missing_capability" for limit in result.limitations)

    preserved = _analyzer(unavailable).analyze(_context(), _base(status=AnalyzerStatus.PASS, score=72))
    assert preserved.status is AnalyzerStatus.PASS
    assert preserved.score == 72


def test_error_is_warn_with_usable_base_and_error_without_one() -> None:
    error = _facts(
        status=PyDrillerExecutionStatus.ERROR,
        unique_commits=0,
        failure_kind=FailureKind.TIMEOUT,
    )
    preserved = _analyzer(error).analyze(_context(), _base(status=AnalyzerStatus.PASS, score=72))
    failed = _analyzer(error).analyze(_context(), _base())

    assert preserved.status is AnalyzerStatus.WARN
    assert preserved.score == 72
    assert any(limit.kind == "timeout" for limit in preserved.limitations)
    assert failed.status is AnalyzerStatus.ERROR
    assert failed.score is None


def test_shallow_history_is_warn_and_exposes_reduced_confidence() -> None:
    result = _analyzer(_facts(shallow=True, confidence=0.70)).analyze(_context(), _base())

    assert result.status is AnalyzerStatus.WARN
    assert result.diagnostics["pydriller_confidence"] == pytest.approx(0.70)
    assert any("shallow" in limit.reason for limit in result.limitations)
    assert result.score is not None and result.score <= 70


def test_overlap_and_double_count_guard_are_diagnostics_only() -> None:
    context = _context().model_copy(
        update={
            "inventory": {
                "git_activity_baseline": GitActivityBaseline(
                    source="sourcecraft.git",
                    commit_hashes=frozenset({"a" * 40}),
                )
            }
        }
    )
    result = _analyzer(_facts()).analyze(context, _base())

    assert result.diagnostics["double_count_guard"] == "pydriller_hash_deduplicated_not_added_to_source_counts"
    assert result.diagnostics["pydriller_overlap_status"] == "measured"
    assert result.source_versions["pydriller"] == "2.12"


def test_commit_history_signal_is_bounded_and_not_a_linear_penalty() -> None:
    small = _analyzer(_facts(unique_commits=4)).analyze(_context(), _base())
    large = _analyzer(_facts(unique_commits=400)).analyze(_context(), _base())

    assert large.score is not None and small.score is not None
    assert large.score > small.score
    assert large.score - small.score < 20
    assert next(metric for metric in small.metrics if metric.name == "pydriller:unique_commits").value == 4
    assert next(metric for metric in large.metrics if metric.name == "pydriller:unique_commits").value == 400
