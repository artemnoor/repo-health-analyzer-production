from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from repo_health.contracts import (
    AnalyzerInput,
    AnalyzerTask,
    DocumentationFacts,
    HealthCategory,
    RepositoryFacts,
    RepositoryRef,
    ResourceLimits,
)


def _task() -> AnalyzerTask:
    repository = RepositoryRef(
        repository_id="acme/repo",
        canonical_uri="https://sourcecraft.example/acme/repo",
        provider="sourcecraft",
        ref="main",
        head_sha="a" * 40,
    )
    facts = RepositoryFacts(
        repository=repository,
        documentation=DocumentationFacts(
            available=True,
            observations=({"key": "lint_score", "value": 92},),
        ),
    )
    analyzer_input = AnalyzerInput(
        analysis_id="analysis-contract",
        repository=repository,
        analyzer_id="repo-health.documentation",
        analyzer_version="repo-health-documentation-v1",
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
        deadline_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    return AnalyzerTask(
        analysis_id=analyzer_input.analysis_id,
        analyzer_id=analyzer_input.analyzer_id,
        analyzer_version=analyzer_input.analyzer_version,
        category=HealthCategory.DOCUMENTATION,
        input=analyzer_input,
        facts_digest=analyzer_input.facts_digest,
        policy_digest=analyzer_input.policy_digest,
        resource_limits=ResourceLimits(timeout_seconds=10),
    )


def test_standalone_task_round_trip_is_deterministic() -> None:
    first = _task()
    second = AnalyzerTask.model_validate_json(first.to_json())

    assert first.task_id == second.task_id
    assert first.to_json() == second.to_json()
    assert first.digest() == second.digest()


def test_standalone_task_does_not_transport_credentials_or_checkout_paths() -> None:
    payload = _task().to_json().casefold()

    assert "token" not in payload
    assert "password" not in payload
    assert "c:\\" not in payload
    assert "raw_payload" not in payload


def test_standalone_contract_rejects_unknown_versions() -> None:
    payload = _task().model_dump(mode="json")
    payload["schema_version"] = "repo-health.v2"

    with pytest.raises(ValidationError, match="unsupported contract schema_version"):
        AnalyzerTask.model_validate(payload)


def test_standalone_contract_rejects_mismatched_task_digests() -> None:
    payload = _task().model_dump(mode="json")
    payload["facts_digest"] = "b" * 64

    with pytest.raises(ValidationError, match="facts_digest"):
        AnalyzerTask.model_validate(payload)
