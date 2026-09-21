"""SonarQube REST/snapshot adapter; failures remain unavailable, never zero."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import httpx
import structlog

from ...contracts.requests import RepositoryRef
from ...contracts.results import CodeHealthFacts, CollectionState, Limitation, RepositoryFacts, SourceStatus

log = structlog.get_logger("repo_health.collection.sonarqube")


class SonarCredentialProvider(Protocol):
    def resolve(self, *, repository: RepositoryRef) -> str | None: ...


class SonarQubeSnapshotError(ValueError):
    pass


class SonarQubeTransportError(RuntimeError):
    pass


class SonarQubeCollector:
    source_id = "sonarqube"

    _METRICS = (
        "ncloc",
        "sqale_index",
        "sqale_rating",
        "maintainability_rating",
        "code_smells",
        "bugs",
        "vulnerabilities",
        "complexity",
        "cognitive_complexity",
        "duplicated_lines_density",
    )

    def __init__(
        self,
        *,
        fetch: Callable[[RepositoryRef], Mapping[str, Any] | str] | None = None,
        base_url: str | None = None,
        credentials: SonarCredentialProvider | None = None,
        transport: Callable[..., Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("SonarQube timeout must be positive")
        self.fetch = fetch
        self.base_url = base_url.rstrip("/") if base_url else None
        self.credentials = credentials
        self._transport = transport
        self.timeout_seconds = timeout_seconds

    def collect(self, repository: RepositoryRef, *, context) -> RepositoryFacts:
        del context
        try:
            if self.fetch is not None:
                return self.from_snapshot(repository, self.fetch(repository))
            snapshot = self._fetch_remote(repository)
            return self.from_snapshot(repository, snapshot)
        except PermissionError:
            return _failure(
                repository,
                "sonarqube.permission_denied",
                "SonarQube rejected the configured credential",
                state=CollectionState.PERMISSION_DENIED,
            )
        except TimeoutError:
            return _failure(
                repository,
                "sonarqube.timeout",
                "SonarQube exceeded its collection timeout",
                state=CollectionState.TIMEOUT,
            )
        except SonarQubeTransportError:
            return _failure(repository, "sonarqube.unavailable", "SonarQube REST service is unavailable")
        except (SonarQubeSnapshotError, OSError, ValueError):
            return _failure(
                repository, "sonarqube.malformed", "SonarQube returned an invalid response", state=CollectionState.ERROR
            )

    def _fetch_remote(self, repository: RepositoryRef) -> Mapping[str, Any] | str:
        if not self.base_url:
            raise SonarQubeTransportError("SonarQube REST integration is not configured")
        if self.credentials is None:
            raise SonarQubeTransportError("SonarQube credential provider is not configured")
        token = self.credentials.resolve(repository=repository)
        if not token:
            raise SonarQubeTransportError("SonarQube credential is not configured")
        params = {
            "component": repository.repository_id,
            "metricKeys": ",".join(self._METRICS),
        }
        url = f"{self.base_url}/api/measures/component"
        try:
            if self._transport is not None:
                response = self._transport(
                    "GET",
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": "repo-health-analyzer/1"},
                    auth=(token, ""),
                    timeout=self.timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                    response = client.get(
                        url,
                        params=params,
                        headers={"Accept": "application/json", "User-Agent": "repo-health-analyzer/1"},
                        auth=(token, ""),
                    )
        except (TimeoutError, httpx.TimeoutException):
            raise
        except Exception as exc:
            log.warning("sonarqube_request_failed", repository_id=repository.repository_id, error_type=type(exc).__name__)
            raise SonarQubeTransportError("SonarQube transport failed") from exc
        status_code = int(response.status_code)
        if status_code in {401, 403}:
            raise PermissionError("SonarQube access denied")
        if status_code == 408 or status_code == 504:
            raise TimeoutError("SonarQube request timed out")
        if status_code < 200 or status_code >= 300:
            raise SonarQubeTransportError(f"SonarQube returned status {status_code}")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise SonarQubeSnapshotError("SonarQube response must be an object")
        headers = getattr(response, "headers", {})
        version = str(headers.get("sonarqube-version") or payload.get("server_version") or "unknown")[:128]
        return {**payload, "server_version": version}

    def from_snapshot(self, repository: RepositoryRef, snapshot: Mapping[str, Any] | str) -> RepositoryFacts:
        payload = _decode(snapshot)
        measures = payload.get("measures") or payload.get("component", {}).get("measures") or {}
        if isinstance(measures, list):
            measures = {
                str(item.get("metric")): item.get("value")
                for item in measures
                if isinstance(item, Mapping) and item.get("metric")
            }
        if not isinstance(measures, Mapping):
            raise SonarQubeSnapshotError("SonarQube measures must be an object or list")
        observations = []
        for key, value in sorted(measures.items(), key=lambda item: str(item[0])):
            scalar = value.get("value") if isinstance(value, Mapping) else value
            if scalar is None or isinstance(scalar, (dict, list)):
                continue
            try:
                number = float(scalar)
                scalar = int(number) if number.is_integer() else number
            except (TypeError, ValueError):
                scalar = str(scalar)[:128]
            observations.append({"key": str(key), "value": scalar})
        if not observations:
            raise SonarQubeSnapshotError("SonarQube response has no measures")
        group = CodeHealthFacts(available=True, observations=tuple(observations))
        status = SourceStatus(
            source_id=self.source_id,
            source_version=str(payload.get("server_version") or "unknown"),
            state=CollectionState.AVAILABLE,
        )
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: status.source_version or "unknown"},
            source_statuses=(status,),
            code_health=group,
        )


def _decode(snapshot: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(snapshot, Mapping):
        return snapshot
    try:
        value = json.loads(snapshot)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SonarQubeSnapshotError("SonarQube response is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise SonarQubeSnapshotError("SonarQube response must be an object")
    return value


def _failure(
    repository: RepositoryRef, code: str, reason: str, *, state: CollectionState = CollectionState.UNAVAILABLE
) -> RepositoryFacts:
    limitation = Limitation(code=code, reason=reason)
    return RepositoryFacts(
        repository=repository,
        source_versions={"sonarqube": "unavailable"},
        source_statuses=(SourceStatus(source_id="sonarqube", state=state, limitations=(limitation,)),),
        code_health=CodeHealthFacts(limitations=(limitation,)),
        limitations=(limitation,),
    )


__all__ = ["SonarQubeCollector", "SonarQubeSnapshotError"]
