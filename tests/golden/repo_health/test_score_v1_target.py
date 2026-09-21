"""Golden gates for the standalone frozen Score v1 policy."""

from __future__ import annotations

import pytest

from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import (
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    HealthCategory,
    ScoreInput,
)
from repo_health.scoring.v1 import ScoreEngineV1


def _repo() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _category(
    analysis_id: str, analyzer_id: str, category: HealthCategory, score: float = 80.0, *, signals=None
) -> CategoryResult:
    return CategoryResult(
        analysis_id=analysis_id,
        analyzer_id=analyzer_id,
        analyzer_version="v1",
        category=category,
        status=CategoryStatus.PASS,
        score=score,
        coverage=Coverage(status="complete", covered=1, total=1),
        confidence=Confidence(value=1.0, level="high"),
        score_signals=signals or {},
        source_versions={"fixture": "v1"},
    )


def _all(*, security_signals=None) -> ScoreInput:
    aid = "analysis-1"
    return ScoreInput(
        analysis_id=aid,
        repository=_repo(),
        documentation=_category(aid, "repo-health.documentation", HealthCategory.DOCUMENTATION),
        activity=_category(aid, "repo-health.activity", HealthCategory.ACTIVITY),
        issues=_category(aid, "repo-health.issues", HealthCategory.ISSUES),
        cicd=_category(aid, "repo-health.cicd", HealthCategory.CICD),
        security=_category(aid, "repo-health.security", HealthCategory.SECURITY, signals=security_signals),
        code_health=_category(aid, "repo-health.code-health", HealthCategory.CODE_HEALTH),
        score_engine_version="repo-health-score-v1",
        policy_digest="a" * 64,
    )


def test_score_v1_complete_and_deterministic() -> None:
    result = ScoreEngineV1().score(_all())
    assert result.overall_score == pytest.approx(80.0)
    assert result.presentation_state == "SCORE"
    assert result.score_status == "pass"
    assert result.model_dump_json() == ScoreEngineV1().score(_all()).model_dump_json()


def test_score_v1_security_cap_is_frozen() -> None:
    result = ScoreEngineV1().score(_all(security_signals={"high_findings": 1}))
    assert result.score_before_caps == 80.0
    assert result.overall_score == 60.0
    assert result.applied_caps == ({"category": "Security", "cap": 60.0, "reason": "confirmed_high"},)
    assert result.score_status == "warn"


def test_score_v1_missing_category_is_not_zero() -> None:
    values = _all().model_copy(update={"issues": None})
    result = ScoreEngineV1().score(values)
    assert result.overall_score == pytest.approx(80.0)
    assert result.presentation_state == "SCORE"
    assert result.score_status == "warn"
    assert result.status.state.value == "partial"


def test_target_formula_matches_legacy_score_v1_on_frozen_complete_case() -> None:
    target = ScoreEngineV1().score(_all())
    # Frozen baseline values from the pre-extraction Score v1 golden fixture.
    assert target.overall_score == pytest.approx(80.0)
    assert target.score_before_caps == pytest.approx(80.0)
    assert target.coverage_k == pytest.approx(1.0)
