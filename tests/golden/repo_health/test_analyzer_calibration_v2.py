"""Golden parity gates for category-local calibration and evidence output."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from repo_health.analyzers import canonical_registry, register_default_factories
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import (
    AnalyzerInput,
    CategoryStatus,
    CicdFacts,
    CodeHealthFacts,
    DocumentationFacts,
    GitFacts,
    IssuesFacts,
    RepositoryFacts,
    SecurityFacts,
)
from repo_health.scoring.calibration_v2 import activity_score, cicd_component_score, documentation_score

REPOSITORY = RepositoryRef(
    repository_id="team/repository",
    canonical_uri="https://sourcecraft.example/team/repository",
    provider="sourcecraft",
    head_sha="a" * 40,
)


def _run(analyzer_id: str, group_name: str, group) -> object:
    register_default_factories()
    spec = canonical_registry.get(analyzer_id)[0]  # type: ignore[index]
    facts = RepositoryFacts(
        repository=REPOSITORY,
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
        **{group_name: group},
    )
    request = AnalyzerInput(
        analysis_id="calibration-v2",
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        repository=REPOSITORY,
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )
    return canonical_registry.run(analyzer_id, request)


def test_calibration_policy_constants_match_frozen_fixtures() -> None:
    assert documentation_score(
        completeness=25.0, instructions=0.0, vale_quality=88.8, readability=51.578947368421055
    ) == pytest.approx(39.93684210526316)
    assert activity_score(
        unique_commits=7.0,
        latest_age_days=4.624826388888889,
        meaningful_ratio=5.0 / 7.0,
        commits_90d=7.0,
        authors_90d=3.0,
        empty_commits=0.0,
    )[0] == pytest.approx(66.23917469369593)
    assert cicd_component_score(
        failure_rate=0.3125,
        failure_streak=0,
        p50_seconds=113.760477,
        p95_seconds=185.12941329999998,
        failure_rate_delta=None,
    )[0] == pytest.approx(75.32894736842104)


def test_six_category_analyzers_emit_policy_score_and_evidence() -> None:
    cases = (
        (
            "repo-health.documentation",
            "documentation",
            DocumentationFacts(
                available=True,
                observations=(
                    {"key": "file_count", "value": 1},
                    {"key": "words", "value": 1000},
                    {"key": "completeness", "value": 100},
                    {"key": "instructions", "value": 100},
                    {"key": "readability", "value": 100},
                    {"key": "vale_quality", "value": 100},
                ),
            ),
            100.0,
            "a08e94e127ea50ec438eee2caae8e093bb248cbe99438ec427a5d492643f90e5",
        ),
        (
            "repo-health.activity",
            "git",
            GitFacts(
                available=True,
                observations=(
                    {"key": "commit_count", "value": 7},
                    {"key": "latest_activity_age_days", "value": 4.624826388888889},
                    {"key": "author_count", "value": 3},
                    {"key": "meaningful_ratio", "value": 5.0 / 7.0},
                    {"key": "commits_90d", "value": 7},
                ),
            ),
            66.23917469369593,
            "01e238f1b8c37016405f14f76b3a7ba7c108aeefed7ce10e4581377e7a03e273",
        ),
        (
            "repo-health.issues",
            "issues",
            IssuesFacts(
                available=True,
                observations=(
                    {"key": "sample_size", "value": 5},
                    {"key": "comments_available", "value": True},
                    {"key": "answered_count", "value": 5},
                    {"key": "response_median_hours", "value": 72},
                    {"key": "response_p75_hours", "value": 168},
                    {"key": "mature_count", "value": 5},
                    {"key": "closed_count", "value": 5},
                    {"key": "close_median_hours", "value": 360},
                    {"key": "close_p75_hours", "value": 720},
                    {"key": "open_count", "value": 0},
                    {"key": "open_age_p75_hours", "value": 720},
                    {"key": "trend_created", "value": 5},
                    {"key": "trend_closed", "value": 5},
                ),
            ),
            80.0,
            "0a4cf8170bcc128faa780b09a7baaffff97ad3fd6d85845e1001bb2112fba08c",
        ),
        (
            "repo-health.cicd",
            "cicd",
            CicdFacts(
                available=True,
                observations=(
                    {"key": "run_count", "value": 5},
                    {"key": "failure_rate", "value": 0},
                    {"key": "failure_streak", "value": 0},
                    {"key": "p50_seconds", "value": 1},
                    {"key": "p95_seconds", "value": 1},
                ),
            ),
            100.0,
            "deaf4d1646fa027fd8ee1dfe2388e1f479939f6f4ee8f000e9a58469c3ddd642",
        ),
        (
            "repo-health.security",
            "security",
            SecurityFacts(
                available=True,
                observations=(
                    {"key": "active_count", "value": 1},
                    {"key": "high_count", "value": 1},
                ),
            ),
            75.0,
            "4ebad7bb832f3b2ff5b9525a94a7dbace6078589d3fbca7d3563b3592185346b",
        ),
        (
            "repo-health.code-health",
            "code_health",
            CodeHealthFacts(
                available=True,
                observations=(
                    {"key": "ncloc", "value": 100},
                    {"key": "maintainability_rating", "value": "A"},
                ),
            ),
            100.0,
            "03f1281de2ab35b7a4b05cc162a1a6acf2c08fc3700483a2bf9a711331e93d1f",
        ),
    )
    for analyzer_id, group_name, group, expected, expected_digest in cases:
        result = _run(analyzer_id, group_name, group)
        assert result.score == pytest.approx(expected)
        assert result.status in {CategoryStatus.PASS, CategoryStatus.WARN}
        assert result.evidence
        assert result.evidence[0].source == analyzer_id
        assert result.coverage.status == "complete"
        assert result.confidence.level == "high"
        assert all(item.redaction == "none" for item in result.evidence)
        assert all(
            set(finding.evidence_ids) <= {item.evidence_id for item in result.evidence} for finding in result.findings
        )
        assert result.digest() == expected_digest
        assert result.digest() == result.model_copy().digest()


def test_code_health_preserves_evidence_when_only_todo_facts_are_available() -> None:
    result = _run(
        "repo-health.code-health",
        "code_health",
        CodeHealthFacts(
            available=True,
            observations=(
                {"key": "source_file_count", "value": 3},
                {"key": "todo_count", "value": 1},
                {"key": "fixme_count", "value": 0},
            ),
        ),
    )

    assert result.score is None
    assert result.status is CategoryStatus.INCONCLUSIVE
    assert len(result.evidence) == 1


def test_code_health_limitations_activate_existing_partial_policy() -> None:
    result = _run(
        "repo-health.code-health",
        "code_health",
        CodeHealthFacts(
            available=True,
            observations=(
                {"key": "ncloc", "value": 100},
                {"key": "maintainability_rating", "value": "A"},
            ),
            limitations=({"code": "sonarqube.unavailable", "reason": "SonarQube is not configured"},),
        ),
    )

    assert result.score is None
    assert result.status is CategoryStatus.INCONCLUSIVE
    assert any(item.code == "code_health.core_unavailable" for item in result.limitations)
