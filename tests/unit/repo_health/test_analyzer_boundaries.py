"""Six-category registry and independent contract-boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from repo_health.analyzers import canonical_registry, register_default_factories
from repo_health.analyzers.security import SecurityAnalyzer
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import (
    AnalyzerInput,
    AppSecScanState,
    CategoryStatus,
    IssuesFacts,
    RepositoryFacts,
    SecurityFacts,
)


def _repo() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _input(analyzer_id: str, *, available: bool = False) -> AnalyzerInput:
    facts = RepositoryFacts(
        repository=_repo(),
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
        issues=IssuesFacts(available=available, observations=({"key": "open_count", "value": 2},) if available else ()),
    )
    spec = canonical_registry.get(analyzer_id)[0]  # type: ignore[index]
    return AnalyzerInput(
        analysis_id="analysis-1",
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        repository=_repo(),
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )


def test_registry_has_exactly_six_and_explicit_factories() -> None:
    register_default_factories()
    assert canonical_registry.ids() == (
        "repo-health.activity",
        "repo-health.cicd",
        "repo-health.code-health",
        "repo-health.documentation",
        "repo-health.issues",
        "repo-health.security",
    )
    assert all(canonical_registry.get(item)[1] is not None for item in canonical_registry.ids())  # type: ignore[index]


def test_unavailable_facts_are_skipped_not_zero() -> None:
    register_default_factories()
    result = canonical_registry.run("repo-health.issues", _input("repo-health.issues"))
    assert result.status is CategoryStatus.SKIPPED
    assert result.score is None


def test_available_facts_return_serializable_category_result() -> None:
    register_default_factories()
    result = canonical_registry.run("repo-health.issues", _input("repo-health.issues", available=True))
    assert result.status is CategoryStatus.PASS
    assert result.score == 100.0
    assert result.digest() == result.model_copy().digest()


@pytest.mark.parametrize("scan_state", [AppSecScanState.NO_SCAN, AppSecScanState.FAILED])
def test_appsec_nonterminal_results_are_inconclusive_not_zero(scan_state: AppSecScanState) -> None:
    facts = RepositoryFacts(
        repository=_repo(),
        security=SecurityFacts(
            available=True,
            scan_state=scan_state,
            observations=(
                {"key": "coverage", "value": 0.0},
                {"key": "confidence", "value": 0.0},
            ),
        ),
    )
    analyzer = SecurityAnalyzer()
    result = analyzer.analyze(
        AnalyzerInput(
            analysis_id="security-lifecycle",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            repository=_repo(),
            analyzer_id=analyzer.id,
            analyzer_version=analyzer.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest=analyzer.policy_digest,
        )
    )

    assert result.status is CategoryStatus.INCONCLUSIVE
    assert result.score is None
    assert result.coverage.status == "unavailable"


def test_appsec_partial_without_measured_findings_is_inconclusive() -> None:
    facts = RepositoryFacts(
        repository=_repo(),
        security=SecurityFacts(
            available=True,
            scan_state=AppSecScanState.PARTIAL,
            observations=({"key": "coverage", "value": 0.5},),
        ),
    )
    analyzer = SecurityAnalyzer()
    result = analyzer.analyze(
        AnalyzerInput(
            analysis_id="security-partial",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            repository=_repo(),
            analyzer_id=analyzer.id,
            analyzer_version=analyzer.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest=analyzer.policy_digest,
        )
    )

    assert result.status is CategoryStatus.INCONCLUSIVE
    assert result.score is None
    assert result.coverage.status == "unavailable"


@pytest.mark.parametrize(
    "module_name",
    [
        "repo_health.analyzers.documentation.analyzer",
        "repo_health.analyzers.activity.analyzer",
        "repo_health.analyzers.issues.analyzer",
        "repo_health.analyzers.cicd.analyzer",
        "repo_health.analyzers.security.analyzer",
        "repo_health.analyzers.code_health.analyzer",
    ],
)
def test_each_analyzer_imports_as_an_independent_boundary(module_name: str) -> None:
    module = __import__(module_name, fromlist=["*"])
    assert any(name.endswith("Analyzer") for name in vars(module))
