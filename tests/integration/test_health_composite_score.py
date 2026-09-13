from datetime import UTC, datetime

from repowise.core.analysis.health.composite import compose_health_score
from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    MetricValue,
)


def test_mixed_native_results_produce_one_explainable_composite() -> None:
    collected = datetime(2026, 9, 10, tzinfo=UTC)
    evidence = EvidenceRef(source="native", source_commit="head", collected_at=collected)
    results = (
        AnalyzerResult(
            analyzer_id="repohealth.baseline",
            analyzer_version="pinned",
            status=AnalyzerStatus.WARN,
            score=90,
            score_dimension="docs",
            evidence=(evidence,),
            available_weight=5,
            total_weight=5,
        ),
        AnalyzerResult(
            analyzer_id="scorecard.local",
            analyzer_version="pinned",
            status=AnalyzerStatus.PASS,
            score=100,
            score_dimension="security",
            evidence=(evidence,),
            available_weight=10,
            total_weight=10,
        ),
        AnalyzerResult(
            analyzer_id="criticality.importance",
            analyzer_version="pinned",
            status=AnalyzerStatus.PASS,
            score=None,
            metrics=(MetricValue(name="criticality", dimension="priority", score=None, denominator=1),),
            evidence=(evidence,),
            available_weight=1,
            total_weight=1,
        ),
    )

    composed = compose_health_score(results, repository_id="fixture")

    assert composed.overall == 97.5
    assert composed.dimensions["docs"] == 90
    assert composed.dimensions["security"] == 100
    assert all(row["dimension"] != "priority" for row in composed.breakdown)
    assert composed.status is AnalyzerStatus.WARN
