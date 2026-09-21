"""SonarQube REST/snapshot adapter; failures remain unavailable, never zero."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from ...contracts.requests import RepositoryRef
from ...contracts.results import CodeHealthFacts, CollectionState, Limitation, RepositoryFacts, SourceStatus


class SonarQubeSnapshotError(ValueError):
    pass


class SonarQubeCollector:
    source_id = "sonarqube"

    def __init__(self, *, fetch: Callable[[RepositoryRef], Mapping[str, Any] | str] | None = None) -> None:
        self.fetch = fetch

    def collect(self, repository: RepositoryRef, *, context) -> RepositoryFacts:
        del context
        if self.fetch is None:
            return _failure(repository, "sonarqube.not_configured", "SonarQube REST integration is not configured")
        try:
            return self.from_snapshot(repository, self.fetch(repository))
        except (SonarQubeSnapshotError, OSError, TimeoutError):
            return _failure(
                repository, "sonarqube.malformed", "SonarQube returned an invalid response", state=CollectionState.ERROR
            )

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
