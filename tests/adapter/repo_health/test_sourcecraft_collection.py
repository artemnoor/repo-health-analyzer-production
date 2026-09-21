"""Contract and failure-isolation tests for the standalone SourceCraft boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from repo_health.collection.ports import CollectionContext
from repo_health.collection.sourcecraft import (
    SourceCraftAppSecCollector,
    SourceCraftAuthError,
    SourceCraftClient,
    SourceCraftCollector,
    SourceCraftResourceCollector,
    SourceCraftUnavailableError,
)
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.contracts.results import CollectionState


class FakeResponse:
    def __init__(self, status_code: int, payload: object, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> object:
        return self._payload


def _repository() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        ref="main",
        head_sha="a" * 40,
    )


def _context() -> CollectionContext:
    request = AnalysisRequest(
        repository=_repository(),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        requested_analyzer_ids=("issues.sourcecraft",),
    )
    return CollectionContext(checkout_path=Path("."), request=request)


def test_sourcecraft_success_normalizes_and_redacts_payload() -> None:
    seen: dict[str, object] = {}

    def transport(method: str, url: str, **kwargs: object) -> FakeResponse:
        seen.update(method=method, url=url, kwargs=kwargs)
        return FakeResponse(
            200,
            {
                "open_count": 3,
                "status": "healthy",
                "api_token": "must-not-cross-boundary",
                "checkout": "C:\\Users\\secret\\repo",
                "nested": {"raw": "payload"},
            },
            {"x-sourcecraft-version": "2026.01"},
        )

    client = SourceCraftClient(
        base_url="https://sourcecraft.example/",
        credentials=lambda_provider("secret-token"),
        transport=transport,
    )
    collector = SourceCraftResourceCollector(
        client=client,
        source_id="issues.sourcecraft",
        path="/api/issues",
        fact_group="issues",
    )

    facts = collector.collect(_repository(), context=_context())

    assert seen["method"] == "GET"
    headers = seen["kwargs"]["headers"]  # type: ignore[index]
    assert headers["Authorization"] == "Bearer secret-token"
    assert [item.key for item in facts.issues.observations] == ["open_count", "status"]
    assert facts.source_versions == {"issues.sourcecraft": "2026.01"}
    assert "secret-token" not in facts.model_dump_json()
    assert "C:\\Users" not in facts.model_dump_json()
    assert facts.source_statuses[0].state is CollectionState.AVAILABLE


def test_sourcecraft_maps_auth_and_not_found_without_score_zero() -> None:
    def denied(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse(401, {"error": "denied"})

    with pytest.raises(SourceCraftAuthError):
        SourceCraftClient(
            base_url="https://sourcecraft.example",
            credentials=lambda_provider("token"),
            transport=denied,
        ).get_json(repository=_repository(), source_id="appsec.sourcecraft", path="/api/appsec")

    def missing(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse(404, {"error": "missing"})

    response = SourceCraftClient(
        base_url="https://sourcecraft.example",
        credentials=lambda_provider(None),
        transport=missing,
    ).get_json(repository=_repository(), source_id="cicd.sourcecraft", path="/api/cicd")
    assert response.state is CollectionState.UNAVAILABLE
    assert response.payload is None
    assert response.limitation is not None


@pytest.mark.parametrize("status", [429, 500, 503])
def test_sourcecraft_maps_transient_statuses_to_unavailable(status: int) -> None:
    def transport(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse(status, {})

    with pytest.raises(SourceCraftUnavailableError):
        SourceCraftClient(
            base_url="https://sourcecraft.example",
            credentials=lambda_provider(None),
            transport=transport,
        ).get_json(repository=_repository(), source_id="issues.sourcecraft", path="/api/issues")


def test_sourcecraft_collector_isolates_one_resource_failure() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        if url.endswith("/bad"):
            return FakeResponse(403, {})
        return FakeResponse(200, {"pipeline_count": 4})

    client = SourceCraftClient(
        base_url="https://sourcecraft.example",
        credentials=lambda_provider("token"),
        transport=transport,
    )
    collector = SourceCraftCollector(
        (
            SourceCraftResourceCollector(
                client=client,
                source_id="cicd.sourcecraft",
                path="/good",
                fact_group="cicd",
            ),
            SourceCraftResourceCollector(
                client=client,
                source_id="security.sourcecraft",
                path="/bad",
                fact_group="security",
            ),
        )
    )

    facts = collector.collect(_repository(), context=_context())

    assert facts.cicd.available is True
    assert facts.security.available is False
    assert any(item.state is CollectionState.PERMISSION_DENIED for item in facts.source_statuses)
    assert any(item.code == "security.sourcecraft.unavailable" for item in facts.limitations)


def test_appsec_collector_uses_scans_groups_findings_chain_and_redacts() -> None:
    calls: list[str] = []

    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("/v1/scans"):
            return FakeResponse(200, {"scans": [{"id": "scan-1", "created_at": "2026-01-01T00:00:00Z"}]})
        if url.endswith("/v1/defect-groups"):
            return FakeResponse(200, {"defect_groups": [{"id": "group-1"}]})
        return FakeResponse(
            200,
            {
                "findings": [
                    {"severity": "critical", "status": "open"},
                    {"severity": "low", "status": "resolved"},
                    {"severity": "high", "status": "open", "token": "must-not-cross"},
                ]
            },
        )

    client = SourceCraftClient(
        base_url="https://sourcecraft.example",
        credentials=lambda_provider("secret-token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftAppSecCollector(client=client).collect(_repository(), context=_context())
    observations = {item.key: item.value for item in facts.security.observations}

    assert calls == ["scans", "defect-groups", "findings"]
    assert observations["active_count"] == 2
    assert observations["critical_count"] == 1
    assert observations["high_count"] == 1
    assert observations["low_count"] == 0
    assert observations["partial"] is False
    assert "secret-token" not in facts.model_dump_json()
    assert "must-not-cross" not in facts.model_dump_json()


def test_appsec_group_failure_is_partial_and_preserves_scan_evidence() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        if url.endswith("/v1/scans"):
            return FakeResponse(200, {"scans": [{"id": "scan-1"}]})
        if url.endswith("/v1/defect-groups"):
            return FakeResponse(200, {"defect_groups": [{"id": "group-1"}]})
        return FakeResponse(503, {})

    client = SourceCraftClient(
        base_url="https://sourcecraft.example",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftAppSecCollector(client=client).collect(_repository(), context=_context())
    observations = {item.key: item.value for item in facts.security.observations}

    assert facts.security.available is True
    assert observations["partial"] is True
    assert observations["groups_with_unavailable_findings"] == 1
    assert any(item.code == "sourcecraft.appsec.findings.1.unavailable" for item in facts.limitations)


class _LambdaProvider:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def resolve(self, *, repository: RepositoryRef) -> str | None:
        del repository
        return self.token


def lambda_provider(token: str | None) -> _LambdaProvider:
    return _LambdaProvider(token)
