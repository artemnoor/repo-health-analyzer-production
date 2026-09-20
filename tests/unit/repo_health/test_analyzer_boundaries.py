from __future__ import annotations

from datetime import UTC, datetime

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerResult, AnalyzerStatus
from repowise.core.repo_health.analyzers.activity import bind_activity_analyzer
from repowise.core.repo_health.analyzers.cicd import bind_cicd_analyzer
from repowise.core.repo_health.analyzers.code_health import bind_code_health_analyzer
from repowise.core.repo_health.analyzers.documentation import bind_documentation_analyzer
from repowise.core.repo_health.analyzers.issues import bind_issues_analyzer
from repowise.core.repo_health.analyzers.security import bind_security_analyzer
from repowise.core.repo_health.contracts.adapters import analyzer_result_to_category_result
from repowise.core.repo_health.contracts.requests import RepositoryRef
from repowise.core.repo_health.contracts.results import AnalyzerInput, RepositoryFacts

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def analyzer_input(analyzer_id: str) -> AnalyzerInput:
    facts = RepositoryFacts()
    return AnalyzerInput(
        analysis_id="analysis-1",
        repository=RepositoryRef(
            repository_id="acme/example",
            canonical_uri="https://github.com/acme/example",
            provider="github",
            ref="main",
            head_sha="a" * 40,
        ),
        analyzer_id=analyzer_id,
        analyzer_version="repo-health-test-v1",
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
        deadline_at=NOW,
    )


def legacy_result(analyzer_id: str) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="legacy-v1",
        status=AnalyzerStatus.PASS,
        score=75,
        available_weight=1,
        total_weight=1,
    )


def adapter_for(canonical_id: str):
    def adapt(result, *, analysis_id: str, category):
        return analyzer_result_to_category_result(
            result,
            analysis_id=analysis_id,
            category=category,
            analyzer_id=canonical_id,
        )

    return adapt


def test_all_six_analyzers_are_independent_injected_boundaries() -> None:
    cases = (
        (
            "repo-health.documentation",
            "vale.documentation",
            bind_documentation_analyzer,
        ),
        ("repo-health.activity", "chaoss.activity", bind_activity_analyzer),
        ("repo-health.issues", "chaoss.issues_prs", bind_issues_analyzer),
        ("repo-health.cicd", "cicd.sourcecraft", bind_cicd_analyzer),
        ("repo-health.security", "sourcecraft.appsec", bind_security_analyzer),
        ("repo-health.code-health", "repowise.health", bind_code_health_analyzer),
    )

    for canonical_id, legacy_id, binder in cases:
        factory = binder(
            lambda _input, legacy_id=legacy_id: legacy_result(legacy_id),
            adapter_for(canonical_id),
        )
        result = factory(analyzer_input(canonical_id))

        assert result.analyzer_id == canonical_id
        assert result.score == 75
        assert result.coverage.covered_weight == 1
        assert result.status.value == "pass"
