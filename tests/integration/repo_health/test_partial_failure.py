from datetime import UTC, datetime

import pytest

from repowise.core.repo_health.analyzers.registry import canonical_registry
from repowise.core.repo_health.contracts import (
    AnalysisRequest,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    RepositoryFacts,
    RepositoryRef,
)
from repowise.core.repo_health.execution import LocalExecutor
from repowise.core.repo_health.orchestration import RepoHealthOrchestrator


@pytest.mark.asyncio
async def test_one_analyzer_failure_leaves_a_partial_six_category_run() -> None:
    repository = RepositoryRef(
        repository_id="repo-1",
        canonical_uri="https://example.test/acme/repo",
        provider="github",
        head_sha="a" * 40,
    )
    request = AnalysisRequest(
        analysis_id="analysis-partial",
        repository=repository,
        requested_analyzer_ids=canonical_registry.ids(),
        as_of=datetime(2026, 9, 20, tzinfo=UTC),
    )
    facts = RepositoryFacts(repository=repository)

    def factory(analyzer_input):
        if analyzer_input.analyzer_id == "repo-health.security":
            raise ValueError("fixture failure")
        spec = canonical_registry.get(analyzer_input.analyzer_id)[0]
        return CategoryResult(
            analysis_id=analyzer_input.analysis_id,
            analyzer_id=spec.id,
            analyzer_version=spec.version,
            category=spec.category,
            status=CategoryStatus.PASS,
            score=80.0,
            coverage=Coverage(status="available", covered=1, total=1),
            confidence=Confidence(value=1.0, level="high"),
        )

    result = await RepoHealthOrchestrator(
        LocalExecutor({analyzer_id: factory for analyzer_id in canonical_registry.ids()})
    ).analyze(request, facts)

    assert result.status.state.value == "partial"
    assert result.status.failed_analyzer_ids == ("repo-health.security",)
    assert len(result.status.completed_analyzer_ids) == 5
    assert len(result.category_results) == 6
