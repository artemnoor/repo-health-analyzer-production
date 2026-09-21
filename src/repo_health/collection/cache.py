"""Deterministic fact-cache identity and bounded transport helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Protocol

from ..contracts.requests import RepositoryRef, canonical_json
from ..contracts.results import CollectionState, Limitation, RepositoryFacts


class FactsSerializationError(ValueError):
    """Raised when normalized facts exceed a transport/persistence limit."""


def facts_cache_key(
    repository: RepositoryRef,
    facts: RepositoryFacts,
    *,
    analyzer_id: str,
    analyzer_version: str,
    policy_digest: str,
    scope: str = "all",
) -> str:
    """Build a cache key that invalidates on head, facts, analyzer, or policy."""

    payload = {
        "repository": repository.model_dump(mode="json"),
        "head_sha": repository.head_sha,
        "facts_digest": facts.digest(),
        "analyzer_id": analyzer_id,
        "analyzer_version": analyzer_version,
        "policy_digest": policy_digest,
        "scope": scope,
    }
    return "repo-health-facts:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def serialize_facts(facts: RepositoryFacts, *, max_bytes: int = 10_000_000) -> str:
    """Serialize redacted facts with an explicit bounded payload size."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    encoded = facts.to_json()
    if len(encoded.encode("utf-8")) > max_bytes:
        raise FactsSerializationError(f"normalized RepositoryFacts exceed {max_bytes} bytes")
    return encoded


def deserialize_facts(payload: str, *, max_bytes: int = 10_000_000) -> RepositoryFacts:
    """Validate worker/cache JSON through the same strict contract."""

    if len(payload.encode("utf-8")) > max_bytes:
        raise FactsSerializationError(f"serialized RepositoryFacts exceed {max_bytes} bytes")
    return RepositoryFacts.model_validate(json.loads(payload))


class FactsCache(Protocol):
    def get(self, key: str) -> RepositoryFacts | None: ...

    def put(self, key: str, facts: RepositoryFacts) -> None: ...


def mark_facts_stale(
    facts: RepositoryFacts,
    *,
    source_ids: Iterable[str] | None = None,
    reason: str = "cached facts are older than the requested freshness policy",
) -> RepositoryFacts:
    """Make stale state visible without fabricating unavailable facts as zero."""

    selected = set(source_ids or (status.source_id for status in facts.source_statuses))
    statuses = tuple(
        status.model_copy(
            update={
                "state": CollectionState.STALE,
                "limitations": (*status.limitations, Limitation(code="stale", reason=reason)),
            }
        )
        if status.source_id in selected
        else status
        for status in facts.source_statuses
    )
    limitations = (*facts.limitations, Limitation(code="stale", reason=reason))
    return facts.model_copy(update={"source_statuses": statuses, "limitations": limitations})


__all__ = [
    "FactsCache",
    "FactsSerializationError",
    "deserialize_facts",
    "facts_cache_key",
    "mark_facts_stale",
    "serialize_facts",
]
