"""Deterministic merge, redaction and cache identity tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from repo_health.collection.cache import FactsSerializationError, deserialize_facts, facts_cache_key, serialize_facts
from repo_health.collection.ports import CollectionContext
from repo_health.collection.service import CollectionService
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.contracts.results import CollectionState, IssuesFacts, RepositoryFacts, SourceStatus


def _repo() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _request() -> AnalysisRequest:
    return AnalysisRequest(repository=_repo(), as_of=datetime(2026, 1, 1, tzinfo=UTC))


class FactsCollector:
    def __init__(self, source_id: str, *, fail: bool = False) -> None:
        self.source_id = source_id
        self.fail = fail

    def collect(self, repository, *, context) -> RepositoryFacts:
        del context
        if self.fail:
            raise RuntimeError("fixture failure")
        status = SourceStatus(source_id=self.source_id, state=CollectionState.AVAILABLE)
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: "fixture-v1"},
            source_statuses=(status,),
            issues=IssuesFacts(available=True, observations=({"key": "open_count", "value": 2},)),
        )


@pytest.mark.asyncio
async def test_collection_service_orders_sources_and_isolates_failures(tmp_path: Path) -> None:
    service = CollectionService((FactsCollector("z-source"), FactsCollector("a-source", fail=True)))
    facts = await service.collect(_request(), checkout_path=tmp_path)
    assert [status.source_id for status in facts.source_statuses] == ["a-source", "z-source"]
    assert facts.issues.available is True
    assert any(status.state is CollectionState.ERROR for status in facts.source_statuses)
    assert any(item.code == "a-source.collection_failed" for item in facts.limitations)


def test_facts_digest_ignores_collection_time_but_changes_on_observation() -> None:
    base = FactsCollector("issues").collect(
        _repo(), context=CollectionContext(checkout_path=Path("."), request=_request())
    )
    changed = base.model_copy(
        update={"issues": IssuesFacts(available=True, observations=({"key": "open_count", "value": 3},))}
    )
    assert base.digest() == base.model_copy(update={"collected_at": datetime(2030, 1, 1, tzinfo=UTC)}).digest()
    assert base.digest() != changed.digest()


def test_facts_serialization_is_bounded_and_round_trips() -> None:
    facts = FactsCollector("issues").collect(
        _repo(), context=CollectionContext(checkout_path=Path("."), request=_request())
    )
    encoded = serialize_facts(facts)
    assert deserialize_facts(encoded).digest() == facts.digest()
    with pytest.raises(FactsSerializationError):
        serialize_facts(facts, max_bytes=1)
    assert facts_cache_key(
        _repo(), facts, analyzer_id="repo-health.issues", analyzer_version="v1", policy_digest="a" * 64
    ).startswith("repo-health-facts:")
