from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from repowise.core.repo_health.collection import (
    CollectionContext,
    CollectionLimits,
    FactsSerializationError,
    deserialize_facts,
    facts_cache_key,
    mark_facts_stale,
    serialize_facts,
)
from repowise.core.repo_health.collection.compatibility import SourceCraftAppSecCollector
from repowise.core.repo_health.contracts import (
    CollectionState,
    RepositoryFacts,
    SourceStatus,
)
from repowise.core.repo_health.contracts.requests import AnalysisRequest, RepositoryRef


def request() -> AnalysisRequest:
    return AnalysisRequest(
        repository={
            "repository_id": "acme/example",
            "canonical_uri": "https://github.com/acme/example",
            "provider": "github",
            "ref": "main",
            "head_sha": "a" * 40,
        },
        as_of=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
    )


def test_collection_context_holds_private_checkout_capability() -> None:
    context = CollectionContext(
        checkout_path=Path("C:/private/checkout"),
        request=request(),
        environment={"SOURCECRAFT_TOKEN": "runtime-only"},
    )

    assert context.checkout_path == Path("C:/private/checkout")
    assert context.request.repository.repository_id == "acme/example"
    assert "SOURCECRAFT_TOKEN" not in context.request.to_json()


def test_collection_limits_are_bounded_positive_values() -> None:
    with pytest.raises(ValueError, match="positive"):
        CollectionLimits(max_files=0)


def test_repository_facts_carries_provenance_status_and_typed_groups() -> None:
    facts = RepositoryFacts(
        repository=RepositoryRef(
            repository_id="acme/example",
            canonical_uri="https://github.com/acme/example",
            provider="github",
            ref="main",
            head_sha="a" * 40,
        ),
        source_snapshot_digest="a" * 64,
        collected_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        source_versions={"git": "2.46", "sourcecraft": "2026-09"},
        source_statuses=(
            SourceStatus(
                source_id="sourcecraft.appsec",
                state=CollectionState.PERMISSION_DENIED,
                limitations=(
                    {"code": "permission_denied", "reason": "AppSec scope unavailable"},
                ),
            ),
            SourceStatus(source_id="git", state=CollectionState.AVAILABLE),
        ),
        capabilities=["git.history"],
        limitations=({"code": "partial", "reason": "AppSec unavailable"},),
    )

    payload = facts.model_dump(mode="json")
    assert facts.source_statuses[0].source_id == "git"
    assert payload["repository"]["repository_id"] == "acme/example"
    assert payload["source_snapshot_digest"] == "a" * 64
    assert "checkout_path" not in payload
    assert "raw_payload" not in payload


def test_source_status_rejects_raw_provider_payloads_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SourceStatus.model_validate(
            {
                "source_id": "sourcecraft.cicd",
                "state": "available",
                "raw_payload": {"token": "secret"},
            }
        )


def test_sourcecraft_appsec_collector_emits_only_normalized_facts() -> None:
    class Transport:
        def fetch(self, request: dict[str, str]) -> dict[str, object]:
            assert request == {"git_repo": "acme/example"}
            return {
                "scans": [{"id": "scan-1"}],
                "groups": [{"id": "group-1", "status": "ACTIVE"}],
                "findings": [
                    {
                        "id": "finding-1",
                        "groupUuid": "group-1",
                        "severity": "HIGH",
                        "status": "ACTIVE",
                        "fileName": "src/app.py",
                        "line": 4,
                    }
                ],
            }

    repository = RepositoryRef(
        repository_id="acme/example",
        canonical_uri="https://github.com/acme/example",
        provider="github",
        ref="main",
        head_sha="a" * 40,
    )
    facts = SourceCraftAppSecCollector(transport=Transport()).collect(
        repository,
        context=CollectionContext(checkout_path=Path("C:/checkout"), request=request()),
    )

    assert facts.security.available is True
    assert facts.source_statuses[0].source_id == "sourcecraft.appsec"
    assert facts.source_statuses[0].state is CollectionState.AVAILABLE
    assert all(isinstance(item.value, (bool, int, float, str, type(None))) for item in facts.security.observations)
    assert "finding-1" not in facts.to_json()


def test_facts_digest_excludes_collection_time_but_cache_key_includes_head_and_policy() -> None:
    first = RepositoryFacts(
        repository=RepositoryRef.model_validate(request().repository),
        collected_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        source_statuses=(
            SourceStatus(
                source_id="git",
                state=CollectionState.AVAILABLE,
                collected_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
            ),
        ),
    )
    second = first.model_copy(
        update={
            "collected_at": first.collected_at + timedelta(hours=1),
            "source_statuses": (
                first.source_statuses[0].model_copy(
                    update={"collected_at": first.source_statuses[0].collected_at + timedelta(hours=1)}
                ),
            ),
        }
    )

    assert first.digest() == second.digest()
    base_key = facts_cache_key(
        first.repository,
        first,
        analyzer_id="documentation",
        analyzer_version="v1",
        policy_digest="a" * 64,
    )
    changed_policy = facts_cache_key(
        first.repository,
        first,
        analyzer_id="documentation",
        analyzer_version="v1",
        policy_digest="b" * 64,
    )
    changed_head = facts_cache_key(
        first.repository.model_copy(update={"head_sha": "b" * 40}),
        first,
        analyzer_id="documentation",
        analyzer_version="v1",
        policy_digest="a" * 64,
    )
    assert base_key != changed_policy
    assert base_key != changed_head


def test_facts_transport_is_bounded_and_stale_state_is_explicit() -> None:
    facts = RepositoryFacts(
        repository=RepositoryRef.model_validate(request().repository),
        source_statuses=(SourceStatus(source_id="git", state=CollectionState.AVAILABLE),),
    )
    restored = deserialize_facts(serialize_facts(facts))
    stale = mark_facts_stale(restored, reason="cache ttl expired")

    assert restored.digest() == facts.digest()
    assert stale.source_statuses[0].state is CollectionState.STALE
    assert any(item.code == "stale" for item in stale.limitations)
    with pytest.raises(ValueError, match="positive"):
        serialize_facts(facts, max_bytes=0)
    with pytest.raises(FactsSerializationError, match="exceed"):
        serialize_facts(facts, max_bytes=10)


def test_fact_observations_reject_paths_and_secret_like_values() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        RepositoryFacts.model_validate(
            {"git": {"observations": [{"key": "path", "value": "C:/checkout/file.py"}]}}
        )
    with pytest.raises(ValidationError, match="secret"):
        RepositoryFacts.model_validate(
            {"security": {"observations": [{"key": "credential", "value": "api_token=abc"}]}}
        )
