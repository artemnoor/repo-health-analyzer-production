from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    MetricValue,
)
from repowise.core.repo_health.contracts.adapters import (
    analyzer_context_to_input,
    analyzer_result_to_category_result,
)
from repowise.core.repo_health.contracts.requests import RepositoryRef, UnsupportedContractVersion
from repowise.core.repo_health.contracts.results import HealthCategory, RepositoryFacts
from repowise.core.repo_health.contracts.versioning import CONTRACT_VERSIONS

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def repository() -> RepositoryRef:
    return RepositoryRef(
        repository_id="acme/example",
        canonical_uri="https://github.com/acme/example",
        provider="github",
        ref="main",
        head_sha="a" * 40,
    )


def legacy_evidence(*, path: str | None = "C:/checkout/docs/README.md") -> EvidenceRef:
    return EvidenceRef(
        source="vale",
        source_commit="a" * 40,
        tool_version="3.12",
        path=path,
        line_start=10,
        line_end=11,
        collected_at=NOW,
        confidence=0.75,
    )


def test_context_adapter_requires_explicit_repository_and_never_serializes_checkout_path() -> None:
    context = AnalyzerContext(
        repo_path=Path("C:/checkout"),
        repo_id="acme/example",
        head_sha="a" * 40,
        as_of_ts=NOW,
    )
    facts = RepositoryFacts()

    adapted = analyzer_context_to_input(
        context,
        analysis_id="analysis-1",
        repository=repository(),
        facts=facts,
        analyzer_id="documentation",
        analyzer_version="v1",
        policy_digest="a" * 64,
    )

    serialized = adapted.model_dump(mode="json")
    assert adapted.facts_digest == facts.digest()
    assert "repo_path" not in serialized
    assert "checkout" not in adapted.to_json()


def test_result_adapter_preserves_score_status_evidence_and_redacts_absolute_paths() -> None:
    evidence = legacy_evidence()
    result = AnalyzerResult(
        analyzer_id="vale.documentation",
        analyzer_version="v1",
        status=AnalyzerStatus.WARN,
        score=82.5,
        metrics=(
            MetricValue(name="lint_score", value=82.5, score=82.5, evidence_refs=(evidence,)),
        ),
        findings=(
            Finding(
                id="legacy-finding-1",
                analyzer_id="vale.documentation",
                subject="docs/README.md",
                dimension="style",
                severity="medium",
                confidence=0.75,
                reason="Heading hierarchy is inconsistent.",
                evidence_refs=(evidence,),
                location=FindingLocation(
                    path="C:/checkout/docs/README.md", line_start=10, line_end=11
                ),
                remediation="Fix the heading hierarchy.",
            ),
        ),
        evidence=(evidence,),
        limitations=(Limitation(reason="optional rule unavailable", kind="missing_capability"),),
        available_weight=0.8,
        total_weight=1.0,
        source_versions={"vale": "3.12"},
        diagnostics={"provider": "vale"},
    )

    adapted = analyzer_result_to_category_result(result, analysis_id="analysis-1")
    serialized = adapted.to_json()

    assert adapted.category is HealthCategory.DOCUMENTATION
    assert adapted.status.value == "warn"
    assert adapted.score == 82.5
    assert adapted.coverage.covered_weight == 0.8
    assert adapted.coverage.total_weight == 1.0
    assert adapted.findings[0].subject == "docs/README.md"
    assert adapted.findings[0].location is not None
    assert adapted.findings[0].location.relative_path is None
    assert adapted.evidence[0].redaction == "partial"
    assert "C:/checkout" not in serialized


def test_unknown_legacy_analyzer_requires_explicit_category() -> None:
    result = AnalyzerResult(
        analyzer_id="vendor.custom",
        analyzer_version="v1",
        status=AnalyzerStatus.SKIPPED,
    )

    with pytest.raises(ValueError, match="category is required"):
        analyzer_result_to_category_result(result, analysis_id="analysis-1")


def test_version_registry_accepts_only_negotiated_supported_version() -> None:
    assert CONTRACT_VERSIONS.negotiate(["repo-health.v1"]) == "repo-health.v1"
    with pytest.raises(UnsupportedContractVersion):
        CONTRACT_VERSIONS.negotiate(["repo-health.v2"])
