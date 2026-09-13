import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.health.composite import compose_health_score
from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
)
from repowise.core.analysis.health.ranking_projection import RankingCandidate, evaluate_eligibility

MATRIX = Path(__file__).parents[1] / "fixtures" / "health" / "calibration-matrix.json"


def _evidence():
    return EvidenceRef(
        source="calibration-fixture",
        source_commit="fixture-head",
        collected_at=datetime(2026, 9, 10, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "case", json.loads(MATRIX.read_text(encoding="utf-8"))["cases"], ids=lambda item: item["id"]
)
def test_language_diverse_health_matrix_preserves_state_semantics(case) -> None:
    kind = case["kind"]
    score = case["score"]
    if score is None:
        result = AnalyzerResult(
            analyzer_id="calibration.tool",
            analyzer_version="1",
            status=AnalyzerStatus.SKIPPED,
            limitations=(),
        )
        composed = compose_health_score([result])
    else:
        result = AnalyzerResult(
            analyzer_id="calibration.score",
            analyzer_version="1",
            status=AnalyzerStatus.PASS,
            score=score,
            score_dimension="code",
            evidence=(_evidence(),),
            available_weight=1,
            total_weight=1,
        )
        composed = compose_health_score([result])

    assert composed.overall == score
    if kind in {"no_git", "missing_tool"}:
        assert composed.overall is None
        assert composed.status is AnalyzerStatus.INCONCLUSIVE

    candidate = RankingCandidate(
        repository_id=case["id"],
        name=case["id"],
        url="",
        visibility="public",
        snapshot_id="snapshot-" + case["id"],
        score_config_digest="calibration-v1",
        overall_score=composed.overall,
        status=composed.status.value,
        dimensions=composed.dimensions,
        languages=tuple(case["languages"]),
        confidence=composed.confidence,
        coverage=composed.coverage,
        evidence_coverage=0.9 if kind != "partial" else 0.2,
        analyzed_at=(
            datetime(2026, 8, 1, tzinfo=UTC)
            if kind == "stale"
            else datetime(2026, 9, 10, tzinfo=UTC)
        ),
        mode="full",
        eligible=composed.overall is not None,
    )
    decision = evaluate_eligibility(candidate, now=datetime(2026, 9, 11, tzinfo=UTC))
    assert decision.eligible is case["expected_eligible"]


def test_matrix_covers_required_edge_classes() -> None:
    cases = json.loads(MATRIX.read_text(encoding="utf-8"))["cases"]
    assert {case["kind"] for case in cases} == {
        "healthy",
        "unhealthy",
        "partial",
        "stale",
        "no_git",
        "missing_tool",
        "tiny",
        "large",
        "monorepo",
        "multi_language",
    }
    assert {language for case in cases for language in case["languages"]} >= {
        "python",
        "rust",
        "go",
        "java",
        "typescript",
    }
