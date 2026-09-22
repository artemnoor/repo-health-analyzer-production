"""Contract and failure-isolation tests for the standalone SourceCraft boundary."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repo_health.analyzers.security import SecurityAnalyzer
from repo_health.collection.ports import CollectionContext
from repo_health.collection.sourcecraft import (
    SourceCraftAppSecCollector,
    SourceCraftAuthError,
    SourceCraftCicdCollector,
    SourceCraftClient,
    SourceCraftCollector,
    SourceCraftIssuesCollector,
    SourceCraftPayloadError,
    SourceCraftResourceCollector,
    SourceCraftUnavailableError,
)
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.contracts.results import AnalyzerInput, AppSecScanState, CollectionState


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
    assert facts.security.scan_state is AppSecScanState.FINISHED_WITH_FINDINGS
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


@pytest.mark.parametrize(
    ("scan_payload", "expected_state"),
    [
        ({"scans": []}, AppSecScanState.NO_SCAN),
        ({"scans": [{"id": "scan-1", "status": "failed"}]}, AppSecScanState.FAILED),
        ({"scans": [{"id": "scan-1", "status": "running"}]}, AppSecScanState.PARTIAL),
    ],
)
def test_appsec_scan_lifecycle_never_fabricates_zero_findings(
    scan_payload: dict[str, object], expected_state: AppSecScanState
) -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        assert url.endswith("/v1/scans")
        return FakeResponse(200, scan_payload)

    client = SourceCraftClient(
        base_url="https://sourcecraft.example",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftAppSecCollector(client=client).collect(_repository(), context=_context())

    assert facts.security.scan_state is expected_state
    observations = {item.key: item.value for item in facts.security.observations}
    assert observations["coverage"] == (0.5 if expected_state is AppSecScanState.PARTIAL else 0.0)
    assert observations["confidence"] == observations["coverage"]


def test_appsec_finished_zero_findings_is_distinct_from_no_scan() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        if url.endswith("/v1/scans"):
            return FakeResponse(200, {"scans": [{"id": "scan-1", "status": "finished"}]})
        if url.endswith("/v1/defect-groups"):
            return FakeResponse(200, {"defect_groups": []})
        raise AssertionError(f"unexpected AppSec request: {url}")

    client = SourceCraftClient(
        base_url="https://sourcecraft.example",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftAppSecCollector(client=client).collect(_repository(), context=_context())

    assert facts.security.scan_state is AppSecScanState.FINISHED_ZERO_FINDINGS
    assert {item.key: item.value for item in facts.security.observations}["coverage"] == 1.0
    analyzer = SecurityAnalyzer()
    result = analyzer.analyze(
        AnalyzerInput(
            analysis_id="appsec-zero",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            repository=_repository(),
            analyzer_id=analyzer.id,
            analyzer_version=analyzer.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest=analyzer.policy_digest,
        )
    )
    assert result.score == 100.0
    assert result.coverage.status == "complete"


def test_official_issues_adapter_follows_page_tokens_and_normalizes_comments() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    pages = deque(
        [
            FakeResponse(
                200,
                {
                    "issues": [
                        {
                            "slug": "1",
                            "status": {"slug": "closed"},
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T01:00:00Z",
                        }
                    ],
                    "next_page_token": "page-2",
                },
            ),
            FakeResponse(
                200,
                {
                    "issues": [
                        {
                            "slug": "2",
                            "status": {"slug": "open"},
                            "created_at": "2026-01-02T00:00:00Z",
                            "updated_at": "2026-01-02T00:00:00Z",
                        }
                    ]
                },
            ),
        ]
    )

    def transport(_method: str, url: str, *, params: dict[str, str], **_kwargs: object) -> FakeResponse:
        calls.append((url, params))
        if url.endswith("/1/comments"):
            return FakeResponse(200, {"issue_comments": [{"created_at": "2026-01-01T00:30:00Z"}]})
        if "/comments" in url:
            return FakeResponse(200, {"issue_comments": []})
        return pages.popleft()

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftIssuesCollector(client=client).collect(_repository(), context=_context())
    observations = {item.key: item.value for item in facts.issues.observations}

    assert calls[0][0].endswith("/repos/team/repository/issues")
    assert calls[1][1]["page_token"] == "page-2"
    assert observations["sample_size"] == 2
    assert observations["closed_count"] == 1
    assert observations["open_count"] == 1
    assert observations["comments_available"] is True
    assert observations["answered_count"] == 1
    assert observations["coverage"] == 1.0


def test_official_issues_adapter_derives_open_age_and_stale_ratio_from_created_at() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        if url.endswith("/comments"):
            return FakeResponse(200, {"issue_comments": []})
        return FakeResponse(
            200,
            {
                "issues": [
                    {
                        "slug": "1",
                        "status": {"slug": "open"},
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-02T00:00:00Z",
                    }
                ]
            },
        )

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    request = AnalysisRequest(
        repository=_repository(),
        as_of=datetime(2026, 2, 5, tzinfo=UTC),
        requested_analyzer_ids=("issues.sourcecraft",),
    )
    context = CollectionContext(checkout_path=Path("."), request=request)
    facts = SourceCraftIssuesCollector(client=client).collect(_repository(), context=context)
    observations = {item.key: item.value for item in facts.issues.observations}

    assert observations["open_age_p75_hours"] == 840.0
    assert observations["stale_count"] == 1
    assert observations["stale_ratio"] == 1.0


def test_official_cicd_adapter_normalizes_terminal_runs_and_duration() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        assert url.endswith("/repos/team/repository/cicd/runs")
        return FakeResponse(
            200,
            {
                "runs": [
                    {
                        "status": "failed",
                        "dates": {
                            "created_at": "2026-01-01T00:00:00Z",
                            "started_at": "2026-01-01T00:00:01Z",
                            "finished_at": "2026-01-01T00:01:01Z",
                        },
                    },
                    {
                        "status": "success",
                        "dates": {
                            "created_at": "2026-01-02T00:00:00Z",
                            "started_at": "2026-01-02T00:00:01Z",
                            "finished_at": "2026-01-02T00:00:31Z",
                        },
                    },
                ]
            },
        )

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftCicdCollector(client=client).collect(_repository(), context=_context())
    observations = {item.key: item.value for item in facts.cicd.observations}

    assert observations["decisive_runs"] == 2
    assert observations["success_count"] == 1
    assert observations["failed_count"] == 1
    assert observations["failure_rate"] == 0.5
    assert observations["success_rate"] == 0.5
    assert observations["last_run_status"] == "success"
    assert observations["p50_seconds"] == 45.0
    assert observations["coverage"] == 1.0


def test_official_issues_adapter_keeps_empty_history_inconclusive() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        assert url.endswith("/repos/team/repository/issues")
        return FakeResponse(200, {"issues": []})

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )

    facts = SourceCraftIssuesCollector(client=client).collect(_repository(), context=_context())

    assert facts.issues.available is True
    assert facts.issues.observations == ()


def test_official_cicd_adapter_does_not_reclassify_cancelled_or_skipped_as_failed() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        assert url.endswith("/repos/team/repository/cicd/runs")
        return FakeResponse(
            200,
            {
                "runs": [
                    {"status": "canceled", "dates": {"created_at": "2026-01-03T00:00:00Z"}},
                    {"status": "skipped", "dates": {"created_at": "2026-01-02T00:00:00Z"}},
                    {"status": "success", "dates": {"created_at": "2026-01-01T00:00:00Z"}},
                ]
            },
        )

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftCicdCollector(client=client).collect(_repository(), context=_context())
    observations = {item.key: item.value for item in facts.cicd.observations}

    assert observations["decisive_runs"] == 3
    assert observations["failed_count"] == 0
    assert observations["failure_rate"] == 0.0
    assert observations["success_count"] == 1


def test_official_cicd_adapter_keeps_empty_history_without_reliability_rate() -> None:
    def transport(_method: str, url: str, **_kwargs: object) -> FakeResponse:
        assert url.endswith("/repos/team/repository/cicd/runs")
        return FakeResponse(200, {"runs": []})

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider("token"),
        transport=transport,
        retry_attempts=1,
    )
    facts = SourceCraftCicdCollector(client=client).collect(_repository(), context=_context())
    observations = {item.key: item.value for item in facts.cicd.observations}

    assert observations["run_count"] == 0
    assert observations["decisive_runs"] == 0
    assert "failure_rate" not in observations
    assert "success_rate" not in observations


def test_sourcecraft_pages_are_bounded_and_marked_partial() -> None:
    def transport(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse(200, {"items": [{"id": "1"}, {"id": "2"}], "next_page_token": "later"})

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider(None),
        transport=transport,
        retry_attempts=1,
    )

    pages = client.get_json_pages(
        repository=_repository(),
        source_id="sourcecraft.issues",
        path="/repos/team/repository/issues",
        rows_key="items",
        max_pages=10,
        max_rows=1,
    )

    assert [row["id"] for row in pages.rows] == ["1"]
    assert pages.complete is False
    assert pages.limitation is not None
    assert pages.limitation.code == "sourcecraft.issues.pages_capped"


def test_sourcecraft_pages_reject_malformed_row_envelope() -> None:
    def transport(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse(200, {"items": {"not": "an-array"}})

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider(None),
        transport=transport,
        retry_attempts=1,
    )

    with pytest.raises(SourceCraftPayloadError, match="missing the items array"):
        client.get_json_pages(
            repository=_repository(),
            source_id="sourcecraft.issues",
            path="/repos/team/repository/issues",
            rows_key="items",
        )


def test_sourcecraft_pages_reject_malformed_or_repeated_page_tokens() -> None:
    responses = deque(
        [
            FakeResponse(200, {"items": [], "next_page_token": "same"}),
            FakeResponse(200, {"items": [], "next_page_token": "same"}),
        ]
    )

    def transport(*_args: object, **_kwargs: object) -> FakeResponse:
        return responses.popleft()

    client = SourceCraftClient(
        base_url="https://api.sourcecraft.tech",
        credentials=lambda_provider(None),
        transport=transport,
        retry_attempts=1,
    )
    with pytest.raises(SourceCraftPayloadError, match="page token"):
        client.get_json_pages(
            repository=_repository(),
            source_id="sourcecraft.issues",
            path="/repos/team/repository/issues",
            rows_key="items",
        )


class _LambdaProvider:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def resolve(self, *, repository: RepositoryRef) -> str | None:
        del repository
        return self.token


def lambda_provider(token: str | None) -> _LambdaProvider:
    return _LambdaProvider(token)
