from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from repo_health.contracts import (
    AnalysisState,
    AnalysisStatus,
    AnalyzerInput,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    Evidence,
    Finding,
    HealthCategory,
    RepoHealthResult,
    RepositoryFacts,
    RepositoryRef,
    ScoreInput,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def repository() -> dict[str, object]:
    return {
        "repository_id": "acme/example",
        "canonical_uri": "https://github.com/acme/example",
        "provider": "github",
        "ref": "main",
        "head_sha": "a" * 40,
    }


def test_repository_ref_without_head_sha_round_trips_through_json() -> None:
    ref = RepositoryRef(
        repository_id="acme/example",
        canonical_uri="https://sourcecraft.example/acme/example",
        provider="sourcecraft",
        ref="main",
    )

    assert RepositoryRef.model_validate_json(ref.to_json()) == ref


def evidence() -> Evidence:
    return Evidence(
        evidence_id="evidence-doc-1",
        source="vale",
        source_version="3.12",
        relative_path="docs/README.md",
        line_start=12,
        line_end=14,
        collected_at=NOW,
        confidence=Confidence(value=0.9, level="high"),
        redaction="partial",
    )


def category(*, finding: Finding | None = None) -> CategoryResult:
    return CategoryResult(
        analysis_id="analysis-1",
        analyzer_id="documentation",
        analyzer_version="v1",
        category=HealthCategory.DOCUMENTATION,
        status=CategoryStatus.WARN,
        score=80,
        findings=(finding,) if finding else (),
        evidence=(evidence(),),
        coverage=Coverage(status="available", covered=8, total=10),
        confidence=Confidence(value=0.8, level="high"),
    )


def test_finding_id_and_result_collections_are_deterministic() -> None:
    finding = Finding(
        analyzer_id="documentation",
        category=HealthCategory.DOCUMENTATION,
        dimension="style",
        severity="medium",
        confidence=Confidence(value=0.8, level="high"),
        reason="The heading hierarchy is inconsistent.",
        location={"relative_path": "docs/README.md", "line_start": 12},
        evidence_ids=["evidence-doc-1"],
    )
    first = category(finding=finding)
    second = CategoryResult.model_validate(
        {**first.model_dump(mode="json"), "findings": list(reversed(first.findings))}
    )

    assert finding.finding_id is not None
    assert first.to_json() == second.to_json()
    assert first.findings[0].finding_id == finding.finding_id


def test_repository_facts_are_typed_and_analyzer_input_checks_digest() -> None:
    facts = RepositoryFacts.model_validate(
        {
            "git": {
                "available": True,
                "observations": [{"key": "commit_count", "value": 42}],
            },
            "documentation": {
                "available": True,
                "observations": [{"key": "lint_score", "value": 91.5}],
            },
            "capabilities": ["git.history", "documentation.lint"],
        }
    )
    analyzer_input = AnalyzerInput(
        analysis_id="analysis-1",
        repository=repository(),
        analyzer_id="documentation",
        analyzer_version="v1",
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
        deadline_at=NOW,
    )

    assert analyzer_input.facts.git.observations[0].value == 42
    assert analyzer_input.facts_digest == facts.digest()

    with pytest.raises(ValidationError, match="facts_digest"):
        AnalyzerInput(
            analysis_id="analysis-1",
            repository=repository(),
            analyzer_id="documentation",
            analyzer_version="v1",
            facts=facts,
            facts_digest="b" * 64,
            policy_digest="a" * 64,
        )


def test_category_result_keeps_unknown_and_partial_explicit() -> None:
    unknown = CategoryResult(
        analysis_id="analysis-1",
        analyzer_id="security",
        analyzer_version="v1",
        category=HealthCategory.SECURITY,
        status=CategoryStatus.INCONCLUSIVE,
        score=None,
        evidence=(),
        coverage=Coverage(status="unavailable", reason="provider unavailable"),
        confidence=Confidence(value=0.0, level="unknown", reason="no source"),
    )

    assert unknown.score is None
    assert unknown.coverage.status == "unavailable"
    assert unknown.confidence.value == 0.0


def test_error_and_skipped_results_cannot_have_scores_or_orphan_evidence() -> None:
    with pytest.raises(ValidationError, match="score must be absent"):
        CategoryResult(
            analysis_id="analysis-1",
            analyzer_id="security",
            analyzer_version="v1",
            category=HealthCategory.SECURITY,
            status=CategoryStatus.ERROR,
            score=0,
            coverage=Coverage(status="unavailable"),
            confidence=Confidence(value=0, level="unknown"),
        )

    finding = Finding(
        analyzer_id="documentation",
        category=HealthCategory.DOCUMENTATION,
        dimension="style",
        severity="low",
        confidence=Confidence(value=0.5, level="medium"),
        reason="Missing evidence link.",
        evidence_ids=["missing-evidence"],
    )
    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        category(finding=finding)


def test_absolute_paths_raw_payloads_and_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="relative"):
        Evidence(
            evidence_id="evidence-1",
            source="tool",
            relative_path="C:/checkout/private.txt",
            collected_at=NOW,
        )

    with pytest.raises(ValidationError, match="extra_forbidden"):
        RepositoryFacts.model_validate({"raw_payload": {"token": "do-not-keep"}})


def test_status_and_public_result_use_explicit_lifecycle_and_category_slots() -> None:
    status = AnalysisStatus(
        analysis_id="analysis-1",
        state=AnalysisState.PARTIAL,
        completed_analyzer_ids=["documentation"],
        failed_analyzer_ids=["security"],
        started_at=NOW,
    )
    result = RepoHealthResult(
        analysis_id="analysis-1",
        repository=repository(),
        status=status,
        overall_score=72.0,
        score_before_caps=90.0,
        score_engine_version="repo-health-score-v1",
        documentation=category(),
    )
    score_input = ScoreInput(
        analysis_id="analysis-1",
        repository=repository(),
        documentation=category(),
        score_engine_version="repo-health-score-v1",
    )

    assert result.documentation is not None
    assert result.security is None
    assert score_input.code_health is None
    assert result.status.state is AnalysisState.PARTIAL


def test_contract_import_does_not_load_api_database_or_analyzer_packages() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import repo_health.contracts; "
                "print(any(name == 'fastapi' or name == 'sqlalchemy' or "
                "name.startswith('repo_health.api') or name.startswith('repo_health.persistence') or "
                "name.startswith('repo_health.analyzers.activity') "
                "for name in sys.modules))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "False"
