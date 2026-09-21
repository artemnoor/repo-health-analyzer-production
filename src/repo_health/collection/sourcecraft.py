"""SourceCraft transport and normalized-facts collection boundaries.

Only this module knows how credentials and HTTP requests reach SourceCraft.
Resource collectors reduce provider payloads to bounded ``RepositoryFacts``;
raw responses never cross into contracts, analyzers, persistence or logs.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from ..contracts.requests import RepositoryRef
from ..contracts.results import (
    CicdFacts,
    CodeHealthFacts,
    CollectionState,
    DocumentationFacts,
    FactGroup,
    FactObservation,
    GitFacts,
    IssuesFacts,
    Limitation,
    RepositoryFacts,
    SecurityFacts,
    SourceStatus,
)
from .ports import CollectionContext, CollectionError, ProviderCollectorPort

log = structlog.get_logger("repo_health.collection.sourcecraft")

_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|bearer|password|secret|token)", re.I)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")
_GROUPS: dict[str, type[FactGroup]] = {
    "documentation": DocumentationFacts,
    "git": GitFacts,
    "issues": IssuesFacts,
    "cicd": CicdFacts,
    "security": SecurityFacts,
    "code_health": CodeHealthFacts,
}


class CredentialProvider(Protocol):
    """Resolve a short-lived credential without exposing its value to callers."""

    def resolve(self, *, repository: RepositoryRef) -> str | None: ...


class EnvironmentCredentialProvider:
    """Read a token from an explicitly configured environment variable."""

    def __init__(self, variable: str = "SOURCECRAFT_TOKEN") -> None:
        normalized = variable.strip()
        if not normalized or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", normalized):
            raise ValueError("credential environment variable must be an uppercase name")
        self.variable = normalized

    def resolve(self, *, repository: RepositoryRef) -> str | None:
        del repository
        token = os.environ.get(self.variable)
        return token.strip() if token and token.strip() else None


class SourceCraftAuthError(CollectionError):
    """SourceCraft rejected credentials or access to a resource."""


class SourceCraftUnavailableError(CollectionError):
    """SourceCraft could not be reached or returned a transient failure."""


class SourceCraftPayloadError(CollectionError):
    """SourceCraft returned a response outside the adapter contract."""


@dataclass(frozen=True, slots=True)
class SourceCraftResponse:
    source_id: str
    source_version: str | None
    state: CollectionState
    payload: Mapping[str, Any] | None
    limitation: Limitation | None = None


class SourceCraftClient:
    """Small HTTP boundary with typed failure mapping and secret-safe logs."""

    def __init__(
        self,
        *,
        base_url: str,
        credentials: CredentialProvider | None = None,
        timeout_seconds: float = 30.0,
        transport: Callable[..., Any] | None = None,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("SourceCraft base_url must use http or https")
        if timeout_seconds <= 0:
            raise ValueError("SourceCraft timeout must be positive")
        if retry_attempts < 1 or retry_attempts > 5:
            raise ValueError("SourceCraft retry_attempts must be between 1 and 5")
        if retry_backoff_seconds < 0 or retry_backoff_seconds > 30:
            raise ValueError("SourceCraft retry backoff must be between 0 and 30 seconds")
        self.base_url = normalized
        self.credentials = credentials or EnvironmentCredentialProvider()
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self._sleeper = sleeper

    def get_json(
        self,
        *,
        repository: RepositoryRef,
        source_id: str,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> SourceCraftResponse:
        if not path.startswith("/") or ".." in path:
            raise ValueError("SourceCraft resource path must be absolute and non-escaping")
        token = self.credentials.resolve(repository=repository)
        headers = {"Accept": "application/json", "User-Agent": "repo-health-analyzer/1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        log.info(
            "sourcecraft_request_start",
            source_id=source_id,
            repository_id=repository.repository_id,
            path=path,
            has_credentials=bool(token),
        )
        for attempt in range(1, self.retry_attempts + 1):
            try:
                if self._transport is not None:
                    response = self._transport(
                        "GET",
                        self.base_url + path,
                        params=dict(params or {}),
                        headers=headers,
                        timeout=self.timeout_seconds,
                    )
                    status_code = int(response.status_code)
                    payload = response.json()
                    response_headers = getattr(response, "headers", {})
                else:
                    import httpx

                    with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                        response = client.get(self.base_url + path, params=params, headers=headers)
                        status_code = response.status_code
                        payload = response.json()
                        response_headers = response.headers
            except Exception as exc:
                if attempt < self.retry_attempts:
                    self._retry(source_id, repository.repository_id, attempt, reason="transport")
                    continue
                log.warning(
                    "sourcecraft_request_failed",
                    source_id=source_id,
                    repository_id=repository.repository_id,
                    error_type=type(exc).__name__,
                    failure_kind="transport",
                )
                raise SourceCraftUnavailableError(f"SourceCraft {source_id} transport failed") from exc

            if status_code in {401, 403}:
                log.warning("sourcecraft_request_denied", source_id=source_id, status_code=status_code)
                raise SourceCraftAuthError(f"SourceCraft {source_id} access denied")
            if status_code == 404:
                return SourceCraftResponse(
                    source_id=source_id,
                    source_version=None,
                    state=CollectionState.UNAVAILABLE,
                    payload=None,
                    limitation=Limitation(
                        code="source_not_found", reason=f"SourceCraft {source_id} resource was not found"
                    ),
                )
            if status_code == 429 or status_code >= 500:
                if attempt < self.retry_attempts:
                    self._retry(source_id, repository.repository_id, attempt, reason=f"status_{status_code}")
                    continue
                log.warning("sourcecraft_request_transient_failure", source_id=source_id, status_code=status_code)
                raise SourceCraftUnavailableError(f"SourceCraft {source_id} returned transient status {status_code}")
            if status_code < 200 or status_code >= 300:
                raise SourceCraftUnavailableError(f"SourceCraft {source_id} returned status {status_code}")
            if not isinstance(payload, Mapping):
                raise SourceCraftPayloadError(f"SourceCraft {source_id} response must be an object")
            version = str(response_headers.get("x-sourcecraft-version") or "unknown")[:128]
            log.info("sourcecraft_request_finished", source_id=source_id, status_code=status_code, attempt=attempt)
            return SourceCraftResponse(source_id, version, CollectionState.AVAILABLE, payload)

        raise AssertionError("SourceCraft retry loop did not return or raise")

    def _retry(self, source_id: str, repository_id: str, attempt: int, *, reason: str) -> None:
        delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
        log.warning(
            "sourcecraft_request_retry",
            source_id=source_id,
            repository_id=repository_id,
            attempt=attempt,
            delay_seconds=delay,
            reason=reason,
        )
        if delay:
            self._sleeper(delay)


def _safe_observations(payload: Mapping[str, Any]) -> tuple[FactObservation, ...]:
    observations: list[FactObservation] = []
    for raw_key, value in sorted(payload.items(), key=lambda item: str(item[0])):
        key = re.sub(r"[^a-z0-9_.-]+", "_", str(raw_key).casefold()).strip("._-")[:128]
        if not key or _SECRET_KEY.search(key):
            continue
        if isinstance(value, (dict, list, tuple)):
            continue
        if isinstance(value, str):
            value = value.strip()[:512]
            if _ABSOLUTE_PATH.match(value) or _SECRET_KEY.search(value):
                continue
        if value is None or isinstance(value, (bool, int, float, str)):
            observations.append(FactObservation(key=key, value=value))
    return tuple(observations)


class SourceCraftResourceCollector:
    """Normalize one configured SourceCraft resource into one fact group."""

    def __init__(
        self,
        *,
        client: SourceCraftClient,
        source_id: str,
        path: str,
        fact_group: str,
        params: Mapping[str, str] | None = None,
    ) -> None:
        if fact_group not in _GROUPS:
            raise ValueError(f"unsupported normalized fact group: {fact_group}")
        self.client = client
        self.source_id = source_id
        self.provider = "sourcecraft"
        self.path = path
        self.fact_group = fact_group
        self.params = dict(params or {})

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        del context
        response = self.client.get_json(
            repository=repository,
            source_id=self.source_id,
            path=self.path,
            params=self.params,
        )
        group_type = _GROUPS[self.fact_group]
        group = group_type(
            available=response.state is CollectionState.AVAILABLE,
            observations=_safe_observations(response.payload or {}),
            limitations=(response.limitation,) if response.limitation else (),
        )
        status = SourceStatus(
            source_id=self.source_id,
            state=response.state,
            source_version=response.source_version,
            collected_at=datetime.now(UTC),
            limitations=(response.limitation,) if response.limitation else (),
        )
        return RepositoryFacts(
            repository=repository,
            collected_at=datetime.now(UTC),
            source_versions={self.source_id: response.source_version or "unknown"},
            source_statuses=(status,),
            **{self.fact_group: group},
        )


class SourceCraftCollector:
    """Merge configured SourceCraft resources into one normalized fact object."""

    source_id = "sourcecraft"
    provider = "sourcecraft"

    def __init__(self, collectors: Sequence[ProviderCollectorPort]) -> None:
        self.collectors = tuple(collectors)
        if not self.collectors:
            raise ValueError("SourceCraftCollector requires at least one resource collector")

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        log.info(
            "sourcecraft_collection_start", repository_id=repository.repository_id, collector_count=len(self.collectors)
        )
        merged = RepositoryFacts(repository=repository, collected_at=datetime.now(UTC))
        for collector in self.collectors:
            try:
                facts = collector.collect(repository, context=context)
                merged = _merge_facts(merged, facts)
            except SourceCraftAuthError as exc:
                merged = _record_failure(merged, collector.source_id, CollectionState.PERMISSION_DENIED, str(exc))
            except SourceCraftUnavailableError as exc:
                merged = _record_failure(merged, collector.source_id, CollectionState.UNAVAILABLE, str(exc))
            except (SourceCraftPayloadError, CollectionError, ValueError) as exc:
                merged = _record_failure(merged, collector.source_id, CollectionState.ERROR, str(exc))
        log.info(
            "sourcecraft_collection_finished", repository_id=repository.repository_id, facts_digest=merged.digest()
        )
        return merged


def _record_failure(facts: RepositoryFacts, source_id: str, state: CollectionState, reason: str) -> RepositoryFacts:
    limitation = Limitation(code=f"{source_id}.unavailable", reason=reason[:512])
    status = SourceStatus(source_id=source_id, state=state, limitations=(limitation,), collected_at=datetime.now(UTC))
    return facts.model_copy(
        update={"source_statuses": (*facts.source_statuses, status), "limitations": (*facts.limitations, limitation)}
    )


def _merge_facts(left: RepositoryFacts, right: RepositoryFacts) -> RepositoryFacts:
    updates: dict[str, Any] = {
        "repository": right.repository or left.repository,
        "collected_at": right.collected_at or left.collected_at,
        "source_versions": {**left.source_versions, **right.source_versions},
        "source_statuses": (*left.source_statuses, *right.source_statuses),
        "capabilities": (*left.capabilities, *right.capabilities),
        "limitations": (*left.limitations, *right.limitations),
    }
    for group in _GROUPS:
        value = getattr(right, group)
        if value.available or value.observations or value.limitations:
            updates[group] = value
    return left.model_copy(update=updates)


class SourceCraftRepositoryCollector(SourceCraftResourceCollector):
    """Repository/ref metadata adapter; payload is reduced to Git facts."""

    def __init__(self, *, client: SourceCraftClient, path: str = "/api/repositories/current") -> None:
        super().__init__(client=client, source_id="sourcecraft.repositories", path=path, fact_group="git")


class SourceCraftIssuesCollector(SourceCraftResourceCollector):
    """Issues resource adapter preserving partial/unavailable source status."""

    def __init__(self, *, client: SourceCraftClient, path: str = "/api/issues") -> None:
        super().__init__(client=client, source_id="sourcecraft.issues", path=path, fact_group="issues")


class SourceCraftCicdCollector(SourceCraftResourceCollector):
    """CI/CD resource adapter for calibration-v2 source observations."""

    def __init__(self, *, client: SourceCraftClient, path: str = "/api/cicd") -> None:
        super().__init__(client=client, source_id="sourcecraft.cicd", path=path, fact_group="cicd")


class SourceCraftAppSecCollector(SourceCraftResourceCollector):
    """AppSec REST adapter; no alternate local security engine is implied."""

    def __init__(self, *, client: SourceCraftClient, path: str = "/api/appsec") -> None:
        super().__init__(client=client, source_id="sourcecraft.appsec", path=path, fact_group="security")


__all__ = [
    "CredentialProvider",
    "EnvironmentCredentialProvider",
    "SourceCraftAppSecCollector",
    "SourceCraftAuthError",
    "SourceCraftCicdCollector",
    "SourceCraftClient",
    "SourceCraftCollector",
    "SourceCraftIssuesCollector",
    "SourceCraftPayloadError",
    "SourceCraftRepositoryCollector",
    "SourceCraftResourceCollector",
    "SourceCraftResponse",
    "SourceCraftUnavailableError",
]
