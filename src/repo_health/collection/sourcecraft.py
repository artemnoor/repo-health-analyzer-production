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
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import structlog

from ..contracts.requests import RepositoryRef
from ..contracts.results import (
    AppSecScanState,
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
from .merge import merge_repository_facts
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
        self._fallback_variables = (
            ("SOURCECRAFT_TOKEN", "SOURCECRAFT_PAT") if normalized == "SOURCECRAFT_TOKEN" else (normalized,)
        )

    def resolve(self, *, repository: RepositoryRef) -> str | None:
        del repository
        for variable in self._fallback_variables:
            token = os.environ.get(variable)
            if token and token.strip():
                return token.strip()
        return None


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


@dataclass(frozen=True, slots=True)
class SourceCraftPageSet:
    """Bounded page-token collection result for one official list endpoint."""

    rows: tuple[Mapping[str, Any], ...]
    responses: tuple[SourceCraftResponse, ...]
    complete: bool
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

    def get_json_pages(
        self,
        *,
        repository: RepositoryRef,
        source_id: str,
        path: str,
        rows_key: str,
        params: Mapping[str, str] | None = None,
        max_pages: int = 100,
        max_rows: int = 10_000,
    ) -> SourceCraftPageSet:
        """Follow the official ``next_page_token`` envelope without raw payload leakage."""

        if not rows_key or max_pages <= 0 or max_rows <= 0:
            raise ValueError("SourceCraft page collection limits must be positive")
        fixed_params = dict(params or {})
        rows: list[Mapping[str, Any]] = []
        responses: list[SourceCraftResponse] = []
        seen_tokens: set[str] = set()
        page_token: str | None = None
        for _page_number in range(1, max_pages + 1):
            page_params = dict(fixed_params)
            if page_token:
                page_params["page_token"] = page_token
            response = self.get_json(
                repository=repository,
                source_id=source_id,
                path=path,
                params=page_params,
            )
            responses.append(response)
            if response.state is not CollectionState.AVAILABLE or response.payload is None:
                return SourceCraftPageSet(
                    rows=tuple(rows),
                    responses=tuple(responses),
                    complete=False,
                    limitation=response.limitation,
                )
            raw_rows = response.payload.get(rows_key)
            if not isinstance(raw_rows, list):
                raise SourceCraftPayloadError(f"SourceCraft {source_id} response is missing the {rows_key} array")
            for row in raw_rows:
                if not isinstance(row, Mapping):
                    raise SourceCraftPayloadError(f"SourceCraft {source_id} contains a malformed {rows_key} row")
                rows.append(row)
                if len(rows) >= max_rows:
                    limitation = Limitation(
                        code=f"{source_id}.pages_capped",
                        reason="SourceCraft pagination was bounded by collection limits",
                    )
                    return SourceCraftPageSet(
                        rows=tuple(rows[:max_rows]),
                        responses=tuple(responses),
                        complete=False,
                        limitation=limitation,
                    )
            next_token = response.payload.get("next_page_token")
            if next_token is None or str(next_token).strip() == "":
                return SourceCraftPageSet(rows=tuple(rows), responses=tuple(responses), complete=True)
            if not isinstance(next_token, str) or next_token in seen_tokens:
                raise SourceCraftPayloadError(f"SourceCraft {source_id} returned an invalid page token")
            seen_tokens.add(next_token)
            page_token = next_token
        limitation = Limitation(
            code=f"{source_id}.pages_capped",
            reason="SourceCraft pagination reached the configured page limit",
        )
        return SourceCraftPageSet(rows=tuple(rows), responses=tuple(responses), complete=False, limitation=limitation)

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
    return merge_repository_facts(left, right)


class SourceCraftRepositoryCollector(SourceCraftResourceCollector):
    """Repository/ref metadata adapter; payload is reduced to Git facts."""

    def __init__(self, *, client: SourceCraftClient, path: str = "/api/repositories/current") -> None:
        super().__init__(client=client, source_id="sourcecraft.repositories", path=path, fact_group="git")


class SourceCraftIssuesCollector(SourceCraftResourceCollector):
    """Official SourceCraft Issues adapter with bounded comment enrichment."""

    def __init__(
        self,
        *,
        client: SourceCraftClient,
        path: str | None = None,
        comments_path_template: str | None = None,
    ) -> None:
        # ``path`` remains injectable for contract tests, while production
        # defaults are built from the official repository route.
        super().__init__(
            client=client,
            source_id="sourcecraft.issues",
            path=path or "",
            fact_group="issues",
        )
        self.comments_path_template = comments_path_template

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        path = self.path or _repository_resource_path(repository, "issues")
        pages = self.client.get_json_pages(
            repository=repository,
            source_id=self.source_id,
            path=path,
            rows_key="issues",
            params={"page_size": "100"},
            max_pages=context.limits.max_provider_pages,
            max_rows=context.limits.max_provider_pages * 100,
        )
        limitations = list(_page_limitations(pages, self.source_id))
        rows = list(pages.rows)
        if not rows:
            # An empty, successfully fetched history is not evidence of a
            # healthy issue process. Keep the provider available for
            # provenance, but leave the analyzer without numeric observations
            # so its existing inconclusive semantics remain intact.
            return _normalized_fact_group(
                repository,
                fact_group="issues",
                responses=pages.responses,
                observations={},
                limitations=limitations,
                available=bool(pages.responses and pages.responses[0].state is CollectionState.AVAILABLE),
            )
        observations: dict[str, object] = {
            "sample_size": len(rows),
            "issue_count": len(rows),
            "open_count": sum(_issue_status(row) in {"open", "in_progress"} for row in rows),
            "closed_count": sum(_issue_status(row) == "closed" for row in rows),
            "coverage": 1.0 if pages.complete else 0.5,
            "confidence": 1.0 if pages.complete else 0.5,
        }
        cutoff = context.request.as_of - timedelta(days=90)
        observations["trend_created"] = sum(_timestamp(row.get("created_at"), cutoff) for row in rows)
        observations["trend_closed"] = sum(
            _issue_status(row) == "closed" and _timestamp(row.get("updated_at"), cutoff) for row in rows
        )

        open_ages = []
        for row in rows:
            if _issue_status(row) not in {"open", "in_progress"}:
                continue
            created = _parse_timestamp(row.get("created_at"))
            if created and created <= context.request.as_of:
                open_ages.append((context.request.as_of - created).total_seconds() / 3600.0)
        if open_ages:
            observations["open_age_p75_hours"] = _percentile(open_ages, 0.75)
            stale_ages = [age for age in open_ages if age >= 30.0 * 24.0]
            observations["stale_count"] = len(stale_ages)
            observations["stale_ratio"] = len(stale_ages) / len(open_ages)

        comment_rows: list[tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]] = []
        responses = list(pages.responses)
        comments_complete = bool(rows)
        comment_limit = min(len(rows), context.limits.max_provider_pages * 100)
        for index, row in enumerate(rows[:comment_limit], start=1):
            slug = _identifier(row, "slug", "id")
            if not slug:
                comments_complete = False
                limitations.append(
                    Limitation(
                        code="sourcecraft.issues.comments_malformed",
                        reason="SourceCraft issue has no stable slug for comment collection",
                    )
                )
                continue
            comments_path = self.comments_path_template
            if comments_path:
                comments_path = comments_path.format(issue_slug=quote(slug, safe=""))
            else:
                comments_path = _repository_resource_path(repository, f"issues/{quote(slug, safe='')}/comments")
            try:
                comments = self.client.get_json_pages(
                    repository=repository,
                    source_id=f"{self.source_id}.comments.{index}",
                    path=comments_path,
                    rows_key="issue_comments",
                    params={"page_size": "100"},
                    max_pages=context.limits.max_provider_pages,
                    max_rows=context.limits.max_provider_pages * 100,
                )
            except (
                SourceCraftAuthError,
                SourceCraftUnavailableError,
                SourceCraftPayloadError,
                CollectionError,
                ValueError,
            ):
                comments_complete = False
                limitations.append(
                    Limitation(
                        code="sourcecraft.issues.comments_unavailable",
                        reason="SourceCraft issue comments could not be collected",
                    )
                )
                continue
            responses.extend(comments.responses)
            limitations.extend(_page_limitations(comments, f"{self.source_id}.comments.{index}"))
            if not comments.complete:
                comments_complete = False
            comment_rows.append((row, comments.rows))

        response_hours = []
        close_hours = []
        answered_count = 0
        for issue, comments in comment_rows:
            if comments:
                answered_count += 1
                created = _parse_timestamp(issue.get("created_at"))
                first_comment = min(
                    (value for value in (_parse_timestamp(item.get("created_at")) for item in comments) if value),
                    default=None,
                )
                if created and first_comment and first_comment >= created:
                    response_hours.append((first_comment - created).total_seconds() / 3600.0)
            if _issue_status(issue) == "closed":
                created = _parse_timestamp(issue.get("created_at"))
                updated = _parse_timestamp(issue.get("updated_at"))
                if created and updated and updated >= created:
                    close_hours.append((updated - created).total_seconds() / 3600.0)
        if comments_complete:
            observations["comments_available"] = bool(rows)
            observations["answered_count"] = answered_count
            if response_hours:
                observations["response_median_hours"] = _percentile(response_hours, 0.50)
                observations["response_p75_hours"] = _percentile(response_hours, 0.75)
        else:
            observations["comments_available"] = False
            limitations.append(
                Limitation(
                    code="sourcecraft.issues.comments_partial",
                    reason="Issue comments are incomplete; response metrics remain unavailable",
                )
            )
        if close_hours:
            observations["close_median_hours"] = _percentile(close_hours, 0.50)
            observations["close_p75_hours"] = _percentile(close_hours, 0.75)
            observations["mature_count"] = len(close_hours)

        return _normalized_fact_group(
            repository,
            fact_group="issues",
            responses=responses,
            observations=observations,
            limitations=limitations,
            available=bool(pages.responses and pages.responses[0].state is CollectionState.AVAILABLE),
        )


class SourceCraftCicdCollector(SourceCraftResourceCollector):
    """Official SourceCraft CI/CD run adapter for calibration-v2 observations."""

    def __init__(self, *, client: SourceCraftClient, path: str | None = None) -> None:
        super().__init__(client=client, source_id="sourcecraft.cicd", path=path or "", fact_group="cicd")

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        path = self.path or _repository_resource_path(repository, "cicd/runs")
        pages = self.client.get_json_pages(
            repository=repository,
            source_id=self.source_id,
            path=path,
            rows_key="runs",
            params={"page_size": "100"},
            max_pages=context.limits.max_provider_pages,
            max_rows=context.limits.max_provider_pages * 100,
        )
        limitations = list(_page_limitations(pages, self.source_id))
        rows = list(pages.rows)
        terminal = [row for row in rows if _ci_status(row) in _TERMINAL_CI_STATUSES]
        failures = [row for row in terminal if _ci_status(row) in _FAILED_CI_STATUSES]
        durations = [duration for row in terminal if (duration := _run_duration_seconds(row)) is not None]
        ordered = sorted(rows, key=_run_sort_key, reverse=True)
        failure_streak = 0
        for row in ordered:
            if _ci_status(row) in _FAILED_CI_STATUSES:
                failure_streak += 1
            else:
                break
        observations: dict[str, object] = {
            "run_count": len(rows),
            "total_runs": len(rows),
            "decisive_runs": len(terminal),
            "success_count": sum(_ci_status(row) == "success" for row in terminal),
            "failed_count": len(failures),
            "failure_rate": len(failures) / len(terminal) if terminal else None,
            "success_rate": sum(_ci_status(row) == "success" for row in terminal) / len(terminal) if terminal else None,
            "failure_streak": failure_streak,
            "coverage": 1.0 if pages.complete else 0.5,
            "confidence": 1.0 if pages.complete else 0.5,
        }
        if durations:
            observations["p50_seconds"] = _percentile(durations, 0.50)
            observations["p95_seconds"] = _percentile(durations, 0.95)
        if ordered:
            observations["last_run_status"] = _ci_status(ordered[0])
        return _normalized_fact_group(
            repository,
            fact_group="cicd",
            responses=pages.responses,
            observations=observations,
            limitations=limitations,
            available=bool(pages.responses and pages.responses[0].state is CollectionState.AVAILABLE),
        )


class SourceCraftAppSecCollector:
    """Bounded SourceCraft AppSec chain: scans → defect groups → findings."""

    source_id = "sourcecraft.appsec"
    provider = "sourcecraft"
    fact_group = "security"

    def __init__(
        self,
        *,
        client: SourceCraftClient,
        scans_path: str = "/v1/scans",
        defect_groups_path: str = "/v1/defect-groups",
        findings_path: str = "/v1/findings",
        max_groups: int = 100,
    ) -> None:
        if max_groups <= 0:
            raise ValueError("max_groups must be positive")
        self.client = client
        self.scans_path = scans_path
        self.defect_groups_path = defect_groups_path
        self.findings_path = findings_path
        self.max_groups = max_groups

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        responses: list[SourceCraftResponse] = []
        limitations: list[Limitation] = []
        observations: dict[str, object] = {}

        scans = self._stage(
            repository,
            source_id="sourcecraft.appsec.scans",
            path=self.scans_path,
            params={"repository_id": repository.repository_id, "ref": repository.ref},
        )
        responses.append(scans)
        if scans.limitation:
            limitations.append(scans.limitation)
        if scans.state is not CollectionState.AVAILABLE or not scans.payload:
            scan_state = (
                AppSecScanState.UNAVAILABLE
                if scans.state in {CollectionState.UNAVAILABLE, CollectionState.PERMISSION_DENIED}
                else AppSecScanState.FAILED
            )
            return self._facts(
                repository,
                responses,
                observations,
                limitations,
                available=scan_state is not AppSecScanState.UNAVAILABLE,
                scan_state=scan_state,
            )

        scan_rows = _payload_rows(scans.payload, "scans", "items", "data")
        if not scan_rows:
            limitation = Limitation(code="appsec.no_scan", reason="SourceCraft returned no completed AppSec scan")
            return self._facts(
                repository,
                responses,
                observations,
                [*limitations, limitation],
                available=True,
                scan_state=AppSecScanState.NO_SCAN,
            )
        selected_scan = _select_latest(scan_rows)
        scan_id = _identifier(selected_scan, "id", "scan_id")
        if not scan_id:
            limitation = Limitation(
                code="appsec.malformed_scan", reason="SourceCraft scan response has no stable identifier"
            )
            return self._facts(
                repository,
                responses,
                observations,
                [*limitations, limitation],
                available=True,
                scan_state=AppSecScanState.FAILED,
            )
        scan_status = _appsec_scan_status(selected_scan)
        if scan_status in {"failed", "error", "cancelled", "canceled"}:
            limitation = Limitation(
                code="appsec.scan_failed", reason="SourceCraft AppSec scan did not finish successfully"
            )
            return self._facts(
                repository,
                responses,
                observations,
                [*limitations, limitation],
                available=True,
                scan_state=AppSecScanState.FAILED,
            )
        if scan_status not in {
            None,
            "finished",
            "completed",
            "complete",
            "success",
            "succeeded",
            "finished_zero_findings",
            "finished_with_findings",
        }:
            limitation = Limitation(code="appsec.scan_partial", reason="SourceCraft AppSec scan is not finished")
            return self._facts(
                repository,
                responses,
                observations,
                [*limitations, limitation],
                available=True,
                scan_state=AppSecScanState.PARTIAL,
            )
        observations["scan_count"] = len(scan_rows)

        groups = self._stage(
            repository,
            source_id="sourcecraft.appsec.defect-groups",
            path=self.defect_groups_path,
            params={"scan_id": scan_id},
        )
        responses.append(groups)
        if groups.limitation:
            limitations.append(groups.limitation)
        if groups.state is not CollectionState.AVAILABLE or groups.payload is None:
            observations["partial"] = True
            return self._facts(
                repository,
                responses,
                observations,
                limitations,
                available=True,
                scan_state=AppSecScanState.PARTIAL,
            )

        group_rows = _payload_rows(groups.payload, "defect_groups", "groups", "items", "data")
        observations["defect_group_count"] = len(group_rows)
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        finding_count = 0
        unavailable_groups = 0
        for index, group in enumerate(group_rows[: self.max_groups], start=1):
            group_id = _identifier(group, "id", "group_id", "defect_group_id")
            if not group_id:
                unavailable_groups += 1
                limitations.append(
                    Limitation(code=f"appsec.group_{index}_malformed", reason="Defect group has no stable identifier")
                )
                continue
            findings = self._stage(
                repository,
                source_id=f"sourcecraft.appsec.findings.{index}",
                path=self.findings_path,
                params={"scan_id": scan_id, "defect_group_id": group_id},
            )
            responses.append(findings)
            if findings.limitation:
                limitations.append(findings.limitation)
            if findings.state is not CollectionState.AVAILABLE or findings.payload is None:
                unavailable_groups += 1
                continue
            rows = _payload_rows(findings.payload, "findings", "items", "data")
            for finding in rows:
                if not _is_active(finding):
                    continue
                finding_count += 1
                severity = _severity(finding)
                if severity in severity_counts:
                    severity_counts[severity] += 1

        observations.update(
            {
                "finding_count": finding_count,
                "active_count": finding_count,
                "critical_count": severity_counts["critical"],
                "high_count": severity_counts["high"],
                "medium_count": severity_counts["medium"],
                "low_count": severity_counts["low"],
                "groups_with_unavailable_findings": unavailable_groups,
                "partial": unavailable_groups > 0 or len(group_rows) > self.max_groups,
            }
        )
        if len(group_rows) > self.max_groups:
            limitations.append(
                Limitation(code="appsec.groups_capped", reason="AppSec defect-group collection was bounded by limits")
            )
        scan_state = (
            AppSecScanState.PARTIAL
            if observations["partial"]
            else AppSecScanState.FINISHED_WITH_FINDINGS
            if finding_count
            else AppSecScanState.FINISHED_ZERO_FINDINGS
        )
        return self._facts(
            repository,
            responses,
            observations,
            limitations,
            available=True,
            scan_state=scan_state,
        )

    def _stage(
        self,
        repository: RepositoryRef,
        *,
        source_id: str,
        path: str,
        params: Mapping[str, str],
    ) -> SourceCraftResponse:
        try:
            return self.client.get_json(repository=repository, source_id=source_id, path=path, params=params)
        except SourceCraftAuthError:
            return SourceCraftResponse(
                source_id=source_id,
                source_version=None,
                state=CollectionState.PERMISSION_DENIED,
                payload=None,
                limitation=Limitation(code=f"{source_id}.permission_denied", reason="SourceCraft denied AppSec access"),
            )
        except SourceCraftUnavailableError:
            return SourceCraftResponse(
                source_id=source_id,
                source_version=None,
                state=CollectionState.UNAVAILABLE,
                payload=None,
                limitation=Limitation(code=f"{source_id}.unavailable", reason="SourceCraft AppSec is unavailable"),
            )
        except (SourceCraftPayloadError, CollectionError, ValueError):
            return SourceCraftResponse(
                source_id=source_id,
                source_version=None,
                state=CollectionState.ERROR,
                payload=None,
                limitation=Limitation(code=f"{source_id}.malformed", reason="SourceCraft AppSec response is malformed"),
            )

    @staticmethod
    def _facts(
        repository: RepositoryRef,
        responses: Sequence[SourceCraftResponse],
        observations: Mapping[str, object],
        limitations: Sequence[Limitation],
        *,
        available: bool,
        scan_state: AppSecScanState,
    ) -> RepositoryFacts:
        statuses = tuple(
            SourceStatus(
                source_id=response.source_id,
                state=response.state,
                source_version=response.source_version,
                collected_at=datetime.now(UTC),
                limitations=(response.limitation,) if response.limitation else (),
            )
            for response in responses
        )
        normalized_observations = dict(observations)
        normalized_observations.setdefault("appsec_scan_state", scan_state.value)
        normalized_observations.setdefault(
            "coverage",
            1.0
            if scan_state
            in {
                AppSecScanState.FINISHED_ZERO_FINDINGS,
                AppSecScanState.FINISHED_WITH_FINDINGS,
            }
            else 0.5
            if scan_state is AppSecScanState.PARTIAL
            else 0.0,
        )
        normalized_observations.setdefault("confidence", normalized_observations["coverage"])
        group = SecurityFacts(
            available=available,
            scan_state=scan_state,
            observations=tuple({"key": key, "value": value} for key, value in normalized_observations.items()),
            limitations=tuple(limitations),
        )
        return RepositoryFacts(
            repository=repository,
            source_versions={response.source_id: response.source_version or "unknown" for response in responses},
            source_statuses=statuses,
            security=group,
            limitations=tuple(limitations),
        )


_TERMINAL_CI_STATUSES = frozenset({"success", "failed", "canceled", "timeout", "skipped", "rejected"})
# Cancellation and skip are observed terminal states, not failures. They stay
# in the denominator as non-success outcomes without being silently reclassified
# as broken runs.
_FAILED_CI_STATUSES = frozenset({"failed", "timeout", "rejected"})


def _repository_resource_path(repository: RepositoryRef, resource: str) -> str:
    """Build an official SourceCraft path from an unambiguous repository identity."""

    parts = [part for part in repository.repository_id.split("/") if part]
    if len(parts) == 2:
        organization, repo = parts
    else:
        parsed = urlsplit(repository.canonical_uri)
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 2 or parsed.username or parsed.password:
            raise SourceCraftPayloadError("SourceCraft repository identity is ambiguous")
        organization, repo = path_parts[:2]
    if not all(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", part) for part in (organization, repo)):
        raise SourceCraftPayloadError("SourceCraft repository identity contains an invalid slug")
    return f"/repos/{quote(organization, safe='')}/{quote(repo, safe='')}/{resource.lstrip('/')}"


def _page_limitations(pages: SourceCraftPageSet, source_id: str) -> tuple[Limitation, ...]:
    limitations: list[Limitation] = []
    if pages.limitation:
        limitations.append(pages.limitation)
    if not pages.responses:
        limitations.append(
            Limitation(code=f"{source_id}.unavailable", reason="SourceCraft returned no provider response")
        )
    return tuple(limitations)


def _normalized_fact_group(
    repository: RepositoryRef,
    *,
    fact_group: str,
    responses: Sequence[SourceCraftResponse],
    observations: Mapping[str, object],
    limitations: Sequence[Limitation],
    available: bool,
) -> RepositoryFacts:
    group_type = _GROUPS[fact_group]
    group = group_type(
        available=available,
        observations=tuple(
            FactObservation(key=key, value=value) for key, value in sorted(observations.items()) if value is not None
        ),
        limitations=tuple(limitations),
    )
    statuses = tuple(
        SourceStatus(
            source_id=response.source_id,
            state=response.state,
            source_version=response.source_version,
            collected_at=datetime.now(UTC),
            limitations=(response.limitation,) if response.limitation else (),
        )
        for response in responses
    )
    return RepositoryFacts(
        repository=repository,
        collected_at=datetime.now(UTC),
        source_versions={response.source_id: response.source_version or "unknown" for response in responses},
        source_statuses=statuses,
        limitations=tuple(limitations),
        **{fact_group: group},
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo and parsed.utcoffset() is not None else None


def _timestamp(value: object, cutoff: datetime) -> bool:
    parsed = _parse_timestamp(value)
    return bool(parsed and parsed >= cutoff)


def _issue_status(row: Mapping[str, Any]) -> str:
    value = row.get("status")
    if isinstance(value, Mapping):
        value = value.get("slug") or value.get("status_type") or value.get("name")
    return str(value or "unknown").casefold().replace(" ", "_")


def _ci_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "unknown").casefold()


def _run_sort_key(row: Mapping[str, Any]) -> datetime:
    dates = row.get("dates")
    if isinstance(dates, Mapping):
        for key in ("finished_at", "updated_at", "started_at", "created_at"):
            parsed = _parse_timestamp(dates.get(key))
            if parsed:
                return parsed
    return datetime.min.replace(tzinfo=UTC)


def _run_duration_seconds(row: Mapping[str, Any]) -> float | None:
    dates = row.get("dates")
    if not isinstance(dates, Mapping):
        return None
    started = _parse_timestamp(dates.get("started_at"))
    finished = _parse_timestamp(dates.get("finished_at"))
    if not started or not finished or finished < started:
        return None
    return (finished - started).total_seconds()


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _payload_rows(payload: Mapping[str, Any] | None, *keys: str) -> list[Mapping[str, Any]]:
    if payload is None:
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    if any(key in payload for key in ("id", "scan_id", "group_id", "defect_group_id")):
        return [payload]
    return []


def _identifier(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip() and len(value.strip()) <= 256:
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _select_latest(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("updated_at") or row.get("created_at") or row.get("finished_at") or ""),
            _identifier(row, "id", "scan_id") or "",
        ),
        reverse=True,
    )[0]


def _appsec_scan_status(row: Mapping[str, Any]) -> str | None:
    for key in ("status", "scan_status", "state"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold().replace("-", "_")
    return None


def _is_active(row: Mapping[str, Any]) -> bool:
    state = str(row.get("status") or row.get("state") or "active").casefold()
    return state not in {"closed", "resolved", "fixed", "suppressed", "false_positive", "inactive"}


def _severity(row: Mapping[str, Any]) -> str:
    value = str(row.get("severity") or row.get("priority") or row.get("level") or "medium").casefold()
    return {"moderate": "medium", "major": "high", "blocker": "critical"}.get(value, value)


__all__ = [
    "CredentialProvider",
    "EnvironmentCredentialProvider",
    "SourceCraftAppSecCollector",
    "SourceCraftAuthError",
    "SourceCraftCicdCollector",
    "SourceCraftClient",
    "SourceCraftCollector",
    "SourceCraftIssuesCollector",
    "SourceCraftPageSet",
    "SourceCraftPayloadError",
    "SourceCraftRepositoryCollector",
    "SourceCraftResourceCollector",
    "SourceCraftResponse",
    "SourceCraftUnavailableError",
]
