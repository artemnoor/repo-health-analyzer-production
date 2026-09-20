from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext
from repowise.core.repo_health.contracts import (
    AnalysisRequest,
    RepositoryRef,
    UnsupportedContractVersion,
    canonical_json,
    parse_analysis_request,
)

AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
HEAD_SHA = "A" * 40


def repository_payload() -> dict[str, object]:
    return {
        "schema_version": "repo-health.v1",
        "repository_id": "acme/example",
        "canonical_uri": "HTTPS://GitHub.com/acme/example/",
        "provider": "GitHub",
        "ref": " refs/heads/main ",
        "head_sha": HEAD_SHA,
    }


def request_payload() -> dict[str, object]:
    return {
        "schema_version": "repo-health.v1",
        "repository": repository_payload(),
        "requested_analyzer_ids": ["security", "documentation", "security"],
        "mode": "full",
        "as_of": AS_OF,
        "config_digest": "ABCDEF123456",
        "policy_digest": "1234567890abcdef",
        "timeout_seconds": 300,
    }


def test_repository_ref_normalizes_identity_and_has_no_local_path() -> None:
    repository = RepositoryRef.model_validate(repository_payload())

    assert repository.canonical_uri == "https://github.com/acme/example"
    assert repository.provider == "github"
    assert repository.ref == "refs/heads/main"
    assert repository.head_sha == HEAD_SHA.lower()
    assert "repo_path" not in repository.model_dump(mode="json")


def test_analysis_request_is_stable_and_derives_an_id() -> None:
    first = parse_analysis_request(request_payload())
    reordered = dict(reversed(list(request_payload().items())))
    reordered["repository"] = dict(reversed(list(repository_payload().items())))
    second = parse_analysis_request(reordered)

    assert first.analysis_id == second.analysis_id
    assert first.requested_analyzer_ids == ("documentation", "security")
    assert first.as_of == AS_OF
    assert first.to_json() == second.to_json()
    assert canonical_json(first.model_dump(mode="json")) == first.to_json()


def test_supplied_analysis_id_is_preserved() -> None:
    payload = request_payload()
    payload["analysis_id"] = "client-analysis-42"

    request = AnalysisRequest.model_validate(payload)

    assert request.analysis_id == "client-analysis-42"


def test_timestamps_are_utc_and_deadline_is_after_as_of() -> None:
    payload = request_payload()
    payload["as_of"] = "2026-09-20T15:00:00+03:00"
    payload["deadline_at"] = "2026-09-20T15:05:00+03:00"

    request = AnalysisRequest.model_validate(payload)

    assert request.as_of == AS_OF
    assert request.deadline_at == AS_OF + timedelta(minutes=5)
    assert request.as_of.tzinfo is UTC


def test_naive_timestamp_and_invalid_deadline_are_rejected() -> None:
    naive = request_payload()
    naive["as_of"] = datetime(2026, 9, 20, 12, 0)
    with pytest.raises(ValidationError, match="aware UTC"):
        AnalysisRequest.model_validate(naive)

    expired = request_payload()
    expired["deadline_at"] = AS_OF
    with pytest.raises(ValidationError, match="deadline_at must be after"):
        AnalysisRequest.model_validate(expired)


def test_local_paths_credentials_secrets_and_extra_fields_cannot_enter_contract() -> None:
    local_path = request_payload()
    local_path["repository"] = {**repository_payload(), "repo_path": str(Path("C:/checkout"))}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AnalysisRequest.model_validate(local_path)

    credentials = request_payload()
    credentials["repository"] = {
        **repository_payload(),
        "canonical_uri": "https://user:password@github.com/acme/example",
    }
    with pytest.raises(ValidationError, match="credentials"):
        AnalysisRequest.model_validate(credentials)

    secret_key = request_payload()
    secret_key["idempotency_key"] = "api_token_123"
    with pytest.raises(ValidationError, match="secret-like"):
        AnalysisRequest.model_validate(secret_key)


def test_schema_version_mismatch_fails_explicitly() -> None:
    payload = request_payload()
    payload["schema_version"] = "repo-health.v2"

    with pytest.raises(UnsupportedContractVersion, match=r"repo-health\.v2"):
        parse_analysis_request(payload)


def test_legacy_analyzer_context_compatibility_import_remains_available() -> None:
    context = AnalyzerContext(
        repo_path=Path("/tmp/repository"),
        repo_id="acme/example",
        head_sha="abc",
        as_of_ts=AS_OF,
    )

    assert context.repo_id == "acme/example"
