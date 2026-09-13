from datetime import UTC, datetime

import pytest

from repowise.core.analysis.health.composite import (
    CompositeScoreConfig,
    compose_health_score,
)
from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    MetricValue,
)


def _evidence(confidence: float = 1.0) -> EvidenceRef:
    return EvidenceRef(
        source="fixture",
        source_commit="head",
        collected_at=datetime(2026, 9, 10, tzinfo=UTC),
        confidence=confidence,
    )


def _result(
    analyzer_id: str,
    score: float | None = None,
    *,
    dimension: str | None = None,
    metric_score: float | None = None,
    denominator: int | None = 1,
    status: AnalyzerStatus = AnalyzerStatus.PASS,
) -> AnalyzerResult:
    ref = _evidence()
    metrics = (
        MetricValue(
            name=f"{dimension or 'unknown'}:score",
            dimension=dimension,
            score=metric_score,
            denominator=denominator,
            evidence_refs=(ref,),
        ),
    ) if metric_score is not None else ()
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="1",
        status=status,
        score=score,
        score_dimension=dimension,
        metrics=metrics,
        evidence=(ref,),
        available_weight=1,
        total_weight=1,
    )


def test_composer_uses_configured_weighted_mean_and_keeps_missing_dimensions_null() -> None:
    result = compose_health_score(
        [_result("fixture.code", score=80, dimension="code"), _result("fixture.security", score=40, dimension="security")]
    )

    assert result.overall == pytest.approx((80 * 0.25 + 40 * 0.15) / 0.40)
    assert result.dimensions["code"] == 80
    assert result.dimensions["tests"] is None
    assert result.available_weight == pytest.approx(0.40)
    assert result.coverage == pytest.approx(0.40)


def test_metric_score_is_used_when_result_has_no_aggregate_score() -> None:
    result = compose_health_score([_result("fixture", dimension="tests", metric_score=0)])

    assert result.overall == 0
    assert result.dimensions["tests"] == 0


def test_one_analyzer_cannot_double_count_dimension() -> None:
    results = [
        _result("fixture", dimension="code", metric_score=20),
        _result("fixture", dimension="code", metric_score=100),
    ]

    result = compose_health_score(results)

    assert result.dimensions["code"] == 60
    assert len([row for row in result.breakdown if row["dimension"] == "code"]) == 1


def test_missing_denominator_is_reported_and_not_zero() -> None:
    result = compose_health_score([_result("fixture", dimension="tests", metric_score=0, denominator=None)])

    assert result.overall is None
    assert result.status is AnalyzerStatus.INCONCLUSIVE
    assert any(item.kind == "insufficient_denominator" for item in result.limitations)


def test_criticality_is_never_a_health_dimension() -> None:
    result = compose_health_score([_result("criticality.importance", score=100, dimension="priority")])

    assert result.overall is None
    assert all(value is None for value in result.dimensions.values())


def test_config_digest_is_stable() -> None:
    config = CompositeScoreConfig.from_mapping({"version": "fixture", "weights": {"code": 1}})

    assert config.digest == CompositeScoreConfig.from_mapping(config.model_dump()).digest
