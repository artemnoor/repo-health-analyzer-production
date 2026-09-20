from datetime import UTC, datetime

from repowise.core.repo_health.api import AnalysisStatusProjection, RepoHealthProjection
from repowise.core.repo_health.contracts import (
    AnalysisState,
    AnalysisStatus,
    RepoHealthResult,
    RepositoryRef,
)


def test_api_projection_is_contract_only_and_keeps_lifecycle_and_score() -> None:
    status = AnalysisStatus(
        analysis_id="analysis-1",
        state=AnalysisState.PARTIAL,
        completed_analyzer_ids=("repo-health.security",),
        failed_analyzer_ids=("repo-health.issues",),
        started_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    result = RepoHealthResult(
        analysis_id="analysis-1",
        repository=RepositoryRef(
            repository_id="repo-1",
            canonical_uri="https://example.test/acme/repo",
            provider="github",
            head_sha="a" * 40,
        ),
        status=status,
        overall_score=61.5,
        score_before_caps=80.0,
        score_engine_version="repo-health-score-v1",
        presentation_state="PROVISIONAL_SCORE",
        coverage=0.75,
        confidence=0.8,
        evidence_coverage=0.7,
        coverage_k=0.6,
        score_status="warn",
    )

    projected = RepoHealthProjection.from_contract(result)
    status_projected = AnalysisStatusProjection.from_contract(status)

    assert projected.repository_id == "repo-1"
    assert projected.overall_score == 61.5
    assert projected.status.state is AnalysisState.PARTIAL
    assert status_projected.failed_analyzer_ids == ("repo-health.issues",)
    assert set(projected.categories) == {
        "documentation",
        "activity",
        "issues",
        "cicd",
        "security",
        "code_health",
    }
