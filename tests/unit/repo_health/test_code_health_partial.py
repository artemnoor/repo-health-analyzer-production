from __future__ import annotations

from datetime import UTC, datetime

from repo_health.analyzers.code_health import CodeHealthAnalyzer
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import (
    AnalyzerInput,
    CodeHealthFacts,
    CollectionState,
    RepositoryFacts,
    SourceStatus,
)

REPOSITORY = RepositoryRef(
    repository_id="acme/example",
    canonical_uri="https://github.com/acme/example",
    provider="github",
    ref="main",
    head_sha="a" * 40,
)


def _result(*, observations: tuple[dict[str, object], ...], statuses: tuple[SourceStatus, ...]):
    facts = RepositoryFacts(
        repository=REPOSITORY,
        code_health=CodeHealthFacts(available=True, observations=observations),
        source_statuses=statuses,
    )
    return CodeHealthAnalyzer().analyze(
        AnalyzerInput(
            analysis_id="code-health-test",
            as_of=datetime(2026, 9, 21, tzinfo=UTC),
            repository=REPOSITORY,
            analyzer_id=CodeHealthAnalyzer.id,
            analyzer_version=CodeHealthAnalyzer.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest="a" * 64,
        )
    )


def _status(source_id: str, state: CollectionState) -> SourceStatus:
    return SourceStatus(source_id=source_id, state=state)


def test_git_sizer_and_todo_are_not_a_surrogate_for_code_health() -> None:
    result = _result(
        observations=(
            {"key": "max_blob_size", "value": 7_000_000},
            {"key": "unique_blob_count", "value": 166_627},
            {"key": "unique_commit_count", "value": 23_635},
            {"key": "source_file_count", "value": 5_082},
            {"key": "todo_count", "value": 811},
        ),
        statuses=(
            _status("git-sizer", CollectionState.AVAILABLE),
            _status("git.todo-history", CollectionState.AVAILABLE),
            _status("sonarqube", CollectionState.UNAVAILABLE),
        ),
    )

    assert result.score is None
    assert result.status.value == "inconclusive"
    assert result.coverage.status == "partial"
    assert (result.coverage.covered, result.coverage.total) == (2, 3)
    assert result.confidence.level in {"unknown", "low"}
    assert result.metrics


def test_large_repository_scale_is_not_a_quality_penalty_when_sonar_is_available() -> None:
    result = _result(
        observations=(
            {"key": "ncloc", "value": 100_000},
            {"key": "maintainability_rating", "value": "A"},
            {"key": "max_blob_size", "value": 7_000_000},
            {"key": "unique_blob_count", "value": 166_627},
        ),
        statuses=(
            _status("git-sizer", CollectionState.AVAILABLE),
            _status("git.todo-history", CollectionState.AVAILABLE),
            _status("sonarqube", CollectionState.AVAILABLE),
        ),
    )

    assert result.score == 100
    assert result.status.value == "pass"
    assert result.coverage.status == "complete"
