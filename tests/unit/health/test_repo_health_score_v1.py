"""Frozen Repo Health Score v1 invariants and migration behavior."""

from __future__ import annotations

from datetime import UTC, datetime

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.health.integrations.contracts import (  # noqa: E402
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
)
from repowise.core.analysis.health.score_engine_v1 import compose_repo_health_score_v1  # noqa: E402


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _result(analyzer_id: str, score: float | None, *, coverage: float = 1.0, confidence: float = 1.0, status: AnalyzerStatus = AnalyzerStatus.PASS, diagnostics: dict | None = None) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="fixture-v1",
        status=status,
        score=score,
        score_dimension={
            "vale.documentation": "docs",
            "chaoss.activity": "history",
            "chaoss.issues_prs": "issues",
            "cicd.sourcecraft": "delivery",
            "sourcecraft.appsec": "security",
            "repowise.health": "code",
        }.get(analyzer_id),
        evidence=(EvidenceRef(source="fixture", collected_at=datetime(2026, 9, 20, tzinfo=UTC), confidence=confidence),),
        available_weight=1 if score is not None else 0,
        total_weight=1,
        diagnostics={"coverage": coverage, "confidence": confidence, **(diagnostics or {})},
    )


def _healthy() -> list[AnalyzerResult]:
    return [
        _result("vale.documentation", 90),
        _result("chaoss.activity", 80),
        _result("chaoss.issues_prs", 70),
        _result("cicd.sourcecraft", 85),
        _result("sourcecraft.appsec", 100),
        _result("repowise.health", 75),
    ]


def test_all_six_use_frozen_weights_and_are_deterministic() -> None:
    first = compose_repo_health_score_v1(_healthy())
    second = compose_repo_health_score_v1(_healthy())
    assert first.overall == second.overall == 83.75
    assert first.presentation_state == "SCORE"
    assert first.coverage_k == 1.0
    assert first.model_dump_json() == second.model_dump_json()


def test_missing_category_is_excluded_from_mean_but_reduces_k() -> None:
    results = _healthy()
    results[-1] = _result("repowise.health", None, status=AnalyzerStatus.SKIPPED, coverage=0, confidence=0)
    score = compose_repo_health_score_v1(results)
    assert score.overall == 85.9375
    assert score.category_scores["Code Health"] is None
    assert score.coverage_k == 0.8
    assert score.presentation_state == "SCORE"


def test_security_critical_is_capped_and_unavailable_is_not_zero() -> None:
    critical = _healthy()
    critical[4] = _result("sourcecraft.appsec", 95, diagnostics={"active_finding_count": 1, "critical_findings": 1})
    capped = compose_repo_health_score_v1(critical)
    assert capped.score_before_cap is not None and capped.score_after_cap == 40
    assert capped.applied_caps[0]["reason"] == "confirmed_critical"

    unavailable = _healthy()
    unavailable[4] = _result("sourcecraft.appsec", None, status=AnalyzerStatus.SKIPPED, coverage=0, confidence=0)
    without_security = compose_repo_health_score_v1(unavailable)
    assert without_security.overall == 79.6875
    assert without_security.category_scores["Security"] is None


def test_insufficient_data_does_not_publish_score() -> None:
    result = compose_repo_health_score_v1(_healthy()[:3])
    assert result.overall is None
    assert result.score_before_cap is not None
    assert result.presentation_state == "INSUFFICIENT_DATA"


def test_duplicate_results_do_not_double_count_a_category() -> None:
    results = _healthy()
    results.append(_result("vale.documentation", 0))
    score = compose_repo_health_score_v1(results)
    assert score.category_scores["Documentation"] == 90
    assert "vale.documentation" in score.excluded_categories
