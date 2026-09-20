from __future__ import annotations

from datetime import UTC, datetime

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
)
from repowise.core.analysis.health.score_engine_v1 import compose_repo_health_score_v1
from repowise.core.repo_health.contracts.adapters import analyzer_result_to_category_result
from repowise.core.repo_health.contracts.requests import RepositoryRef
from repowise.core.repo_health.contracts.results import ScoreInput
from repowise.core.repo_health.scoring import FrozenRepoHealthScorePort

NOW = datetime(2026, 9, 20, tzinfo=UTC)
LEGACY_IDS = {
    "documentation": "vale.documentation",
    "activity": "chaoss.activity",
    "issues": "chaoss.issues_prs",
    "cicd": "cicd.sourcecraft",
    "security": "sourcecraft.appsec",
    "code_health": "repowise.health",
}
CANONICAL_IDS = {key: f"repo-health.{key.replace('_', '-')}" for key in LEGACY_IDS}


def legacy_result(analyzer_id: str, score: float | None, **diagnostics: int) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="fixture-v1",
        status=AnalyzerStatus.PASS if score is not None else AnalyzerStatus.SKIPPED,
        score=score,
        evidence=(EvidenceRef(source="fixture", collected_at=NOW, confidence=1.0),),
        available_weight=1 if score is not None else 0,
        total_weight=1,
        diagnostics={"coverage": 1 if score is not None else 0, "confidence": 1 if score is not None else 0, **diagnostics},
    )


def to_category(key: str, result: AnalyzerResult):
    return analyzer_result_to_category_result(
        result,
        analysis_id="analysis-score-1",
        analyzer_id=CANONICAL_IDS[key],
    )


def score_input(results: dict[str, AnalyzerResult]) -> ScoreInput:
    categories = {key: to_category(key, result) for key, result in results.items()}
    return ScoreInput(
        analysis_id="analysis-score-1",
        repository=RepositoryRef(
            repository_id="acme/example",
            canonical_uri="https://github.com/acme/example",
            provider="github",
            ref="main",
            head_sha="a" * 40,
        ),
        score_engine_version="repo-health-score-v1",
        documentation=categories.get("documentation"),
        activity=categories.get("activity"),
        issues=categories.get("issues"),
        cicd=categories.get("cicd"),
        security=categories.get("security"),
        code_health=categories.get("code_health"),
    )


def test_score_port_matches_frozen_v1_for_healthy_fixture() -> None:
    results = {
        "documentation": legacy_result(LEGACY_IDS["documentation"], 90),
        "activity": legacy_result(LEGACY_IDS["activity"], 80),
        "issues": legacy_result(LEGACY_IDS["issues"], 70),
        "cicd": legacy_result(LEGACY_IDS["cicd"], 85),
        "security": legacy_result(LEGACY_IDS["security"], 100),
        "code_health": legacy_result(LEGACY_IDS["code_health"], 75),
    }
    expected = compose_repo_health_score_v1(results.values())
    actual = FrozenRepoHealthScorePort().score(score_input(results))

    assert actual.overall_score == expected.overall
    assert actual.score_before_caps == expected.score_before_cap
    assert actual.coverage_k == expected.coverage_k
    assert actual.confidence == expected.confidence
    assert actual.evidence_coverage == expected.evidence_coverage
    assert actual.presentation_state == expected.presentation_state
    assert actual.score_config_digest == expected.score_config_digest


def test_score_port_preserves_security_cap_and_unavailable_category() -> None:
    results = {
        "documentation": legacy_result(LEGACY_IDS["documentation"], 90),
        "activity": legacy_result(LEGACY_IDS["activity"], 80),
        "issues": legacy_result(LEGACY_IDS["issues"], 70),
        "cicd": legacy_result(LEGACY_IDS["cicd"], 85),
        "security": legacy_result(
            LEGACY_IDS["security"],
            95,
            active_finding_count=1,
            critical_findings=1,
        ),
        "code_health": legacy_result(LEGACY_IDS["code_health"], 75),
    }
    actual = FrozenRepoHealthScorePort().score(score_input(results))

    assert actual.score_before_caps == 82.75
    assert actual.overall_score == 40
    assert actual.applied_caps[0]["reason"] == "confirmed_critical"

    results["code_health"] = legacy_result(LEGACY_IDS["code_health"], None)
    unavailable = FrozenRepoHealthScorePort().score(score_input(results))
    assert unavailable.code_health is not None
    assert unavailable.code_health.score is None
