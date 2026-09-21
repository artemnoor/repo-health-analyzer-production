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
from repo_health.scoring.v1 import DEFAULT_REPO_HEALTH_WEIGHTS, ScoreEngineV1


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


@pytest.mark.parametrize(
    ("signals", "cap_reason"),
    [
        ({"critical_findings": 1}, "confirmed_critical"),
        ({"confirmed_secret_count": 1}, "confirmed_secret"),
        ({"secret_findings": 1, "critical_findings": 1}, "confirmed_secret"),
    ],
)
def test_score_v1_critical_and_secret_caps_are_frozen(signals: dict[str, int], cap_reason: str) -> None:
    result = ScoreEngineV1().score(_all(security_signals=signals))
    assert result.score_before_caps == pytest.approx(80.0)
    assert result.overall_score == pytest.approx(40.0)
    assert result.applied_caps == ({"category": "Security", "cap": 40.0, "reason": cap_reason},)
    assert result.score_status == "fail"


def test_score_v1_weights_and_insufficient_data_thresholds_are_frozen() -> None:
    assert DEFAULT_REPO_HEALTH_WEIGHTS == {
        "Documentation": 0.15,
        "Activity": 0.15,
        "Issues": 0.15,
        "CI/CD": 0.15,
        "Security": 0.20,
        "Code Health": 0.20,
    }
    partial = _all().model_copy(update={"issues": None, "cicd": None})
    provisional = ScoreEngineV1().score(partial)
    assert provisional.presentation_state == "PROVISIONAL_SCORE"
    assert provisional.score_status == "warn"
    assert provisional.coverage_k == pytest.approx(0.70)

    insufficient = _all().model_copy(
        update={
            "documentation": _category(
                "analysis-1", "repo-health.documentation", HealthCategory.DOCUMENTATION, signals={}
            ).model_copy(update={"coverage": Coverage(status="partial", covered=0, total=1)}),
            "activity": None,
            "issues": None,
            "cicd": None,
            "security": None,
            "code_health": None,
        }
    )
    result = ScoreEngineV1().score(insufficient)
    assert result.overall_score is None
    assert result.presentation_state == "INSUFFICIENT_DATA"
    assert result.score_status == "inconclusive"


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
