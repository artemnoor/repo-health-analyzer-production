"""Historical v1 envelope replay gates."""

from __future__ import annotations

import pytest

from repo_health.contracts.requests import RepositoryRef
from repo_health.persistence import LegacyReplayError, replay_legacy_score


def _repository() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _payload() -> dict[str, object]:
    names = ("Documentation", "Activity", "Issues", "CI/CD", "Security", "Code Health")
    return {
        "score_engine_version": "repo-health-score-v1",
        "overall": 80.0,
        "score_before_cap": 80.0,
        "presentation_state": "SCORE",
        "score_status": "pass",
        "category_scores": {name: 80.0 for name in names},
        "category_coverage": {name: 100.0 for name in names},
        "category_confidence": {name: 1.0 for name in names},
        "coverage_k": 1.0,
        "confidence": 1.0,
        "evidence_coverage": 0.0,
        "applied_caps": [],
    }


def test_legacy_v1_replay_preserves_score_and_marks_missing_evidence() -> None:
    result = replay_legacy_score(_payload(), analysis_id="legacy-analysis", repository=_repository())
    assert result.overall_score == pytest.approx(80.0)
    assert result.score_before_caps == pytest.approx(80.0)
    assert result.presentation_state == "SCORE"
    assert result.status.state.value == "completed"
    assert result.documentation is not None
    assert result.documentation.coverage.covered == 100
    assert any(item.code == "legacy.evidence_unavailable" for item in result.limitations)


def test_legacy_unknown_fields_are_explicit_and_unknown_version_is_unavailable() -> None:
    payload = _payload() | {"old_private_field": "not mapped"}
    result = replay_legacy_score(payload, analysis_id="legacy-analysis", repository=_repository())
    assert any(item.code == "legacy.unmapped_fields" for item in result.limitations)

    unavailable = replay_legacy_score(
        _payload() | {"score_engine_version": "composite-v0"},
        analysis_id="legacy-analysis",
        repository=_repository(),
    )
    assert unavailable.overall_score is None
    assert unavailable.presentation_state == "INSUFFICIENT_DATA"
    assert any(item.code == "legacy_unavailable" for item in unavailable.limitations)


def test_legacy_malformed_category_map_is_rejected() -> None:
    with pytest.raises(LegacyReplayError):
        replay_legacy_score(
            _payload() | {"category_scores": []}, analysis_id="legacy-analysis", repository=_repository()
        )
