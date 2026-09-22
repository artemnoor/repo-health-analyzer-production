from __future__ import annotations

from datetime import UTC, datetime

from repo_health.analyzers.documentation import DocumentationAnalyzer
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import AnalyzerInput, DocumentationFacts, RepositoryFacts

REPOSITORY = RepositoryRef(
    repository_id="acme/example",
    canonical_uri="https://github.com/acme/example",
    provider="github",
    ref="main",
    head_sha="a" * 40,
)


def _result(observations: tuple[dict[str, object], ...]):
    facts = RepositoryFacts(
        repository=REPOSITORY,
        collected_at=datetime(2026, 9, 21, tzinfo=UTC),
        documentation=DocumentationFacts(available=True, observations=observations),
    )
    return DocumentationAnalyzer().analyze(
        AnalyzerInput(
            analysis_id="documentation-test",
            as_of=datetime(2026, 9, 21, tzinfo=UTC),
            repository=REPOSITORY,
            analyzer_id=DocumentationAnalyzer.id,
            analyzer_version=DocumentationAnalyzer.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest="a" * 64,
        )
    )


def test_zero_vale_findings_do_not_imply_complete_documentation() -> None:
    minimal = _result(
        (
            {"key": "analyzed_files", "value": 1},
            {"key": "discovered_files", "value": 1},
            {"key": "words", "value": 3},
            {"key": "completeness", "value": 40},
            {"key": "instructions", "value": 0},
            {"key": "readability", "value": 100},
            {"key": "weighted_finding_points", "value": 0},
        )
    )

    assert minimal.score is not None
    assert minimal.score < 80
    assert minimal.metrics


def test_documentation_surface_features_create_meaningful_variance() -> None:
    tiny = _result(
        (
            {"key": "analyzed_files", "value": 1},
            {"key": "discovered_files", "value": 1},
            {"key": "words", "value": 3},
            {"key": "completeness", "value": 40},
            {"key": "instructions", "value": 0},
            {"key": "readability", "value": 100},
            {"key": "weighted_finding_points", "value": 0},
        )
    )
    mature = _result(
        (
            {"key": "analyzed_files", "value": 8},
            {"key": "discovered_files", "value": 8},
            {"key": "words", "value": 1800},
            {"key": "completeness", "value": 100},
            {"key": "instructions", "value": 100},
            {"key": "readability", "value": 88},
            {"key": "weighted_finding_points", "value": 0},
        )
    )

    assert tiny.score is not None and mature.score is not None
    assert mature.score - tiny.score > 20
