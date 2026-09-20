"""SourceCraft AppSec adapter and normalized security facts.

The adapter owns the SourceCraft AppSec REST boundary.  The analyzer never
sees transport responses, authentication headers, or provider-specific group
objects; it receives only normalized findings and coverage diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import structlog

from .contracts import AnalyzerContext, EvidenceRef, Finding, FindingLocation

log = structlog.get_logger("health.security.appsec")

APPSEC_SOURCE_COMMIT = "sourcecraft-appsec-rest-v1"
APPSEC_ADAPTER_VERSION = "sourcecraft-appsec-adapter-v1"
APPSEC_BASE_URL = "https://appsec.sourcecraft.tech"


class AppSecDataStatus(StrEnum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AppSecFindingFact:
    finding_id: str
    group_id: str | None
    scan_id: str | None
    engine: str | None
    engine_type: str | None
    rule: str | None
    severity: str
    state: str
    file: str | None
    line: int | None
    message: str | None
    deep_link: str | None
    json_pointer: str

    @property
    def is_active(self) -> bool:
        return self.state == "ACTIVE"


@dataclass(frozen=True)
class AppSecFacts:
    status: AppSecDataStatus
    repository_id: str | None
    scans_count: int
    groups_count: int
    findings: tuple[AppSecFindingFact, ...]
    coverage: float
    confidence: float
    source_version: str = APPSEC_SOURCE_COMMIT
    failure_kind: str | None = None
    groups_with_unavailable_findings: int = 0
    diagnostics: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage", max(0.0, min(1.0, float(self.coverage))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics or {}))

    @property
    def active_findings(self) -> tuple[AppSecFindingFact, ...]:
        return tuple(item for item in self.findings if item.is_active)

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "repository_id": self.repository_id,
            "scans_count": self.scans_count,
            "groups_count": self.groups_count,
            "finding_count": len(self.findings),
            "active_finding_count": len(self.active_findings),
            "coverage": self.coverage,
            "confidence": self.confidence,
            "failure_kind": self.failure_kind,
            "groups_with_unavailable_findings": self.groups_with_unavailable_findings,
            **dict(self.diagnostics),
        }


class AppSecTransport(Protocol):
    def fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class AppSecUnavailableError(RuntimeError):
    """The provider was reachable but the security resource is unavailable."""


class AppSecPayloadError(ValueError):
    """The provider returned a response outside the supported JSON contract."""


class SourceCraftAppSecHTTPTransport:
    """Minimal REST client for the validated SourceCraft AppSec path."""

    def __init__(
        self,
        base_url: str = APPSEC_BASE_URL,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        page_size: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or os.environ.get("SOURCECRAFT_PAT", "")
        self.timeout = max(1.0, float(timeout))
        self.page_size = max(1, min(100, int(page_size)))

    def fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        repository_id = str(request.get("git_repo") or "").strip()
        if not repository_id:
            raise AppSecUnavailableError("SourceCraft AppSec requires gitRepo")
        if not self.token:
            raise AppSecUnavailableError("SOURCECRAFT_PAT is not configured")
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - project dependency
            raise RuntimeError("httpx is required for SourceCraft AppSec transport") from exc

        headers = {"Authorization": f"Bearer {self.token}"}
        with httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout, follow_redirects=True) as client:
            scans_response = client.get("/v1/scans", params={"gitRepo": repository_id, "pageSize": self.page_size})
            if scans_response.status_code in {401, 403, 404}:
                raise AppSecUnavailableError(f"SourceCraft AppSec unavailable ({scans_response.status_code})")
            scans_response.raise_for_status()
            scans_payload = scans_response.json()
            scans = _rows(scans_payload, "data", "scans")
            groups: list[dict[str, Any]] = []
            finding_rows: list[dict[str, Any]] = []
            group_errors = 0
            finding_errors = 0
            for scan in scans:
                scan_id = _text(_first(scan, "uuid", "id", "scanUuid"))
                if not scan_id:
                    continue
                response = client.get(
                    "/v1/defect-groups",
                    params={"scanUuid": scan_id, "gitRepo": repository_id},
                )
                if response.status_code in {401, 403, 404}:
                    group_errors += 1
                    continue
                response.raise_for_status()
                payload = response.json()
                for group in _rows(payload, "data", "groups"):
                    group_copy = dict(group)
                    group_copy["scanUuid"] = scan_id
                    groups.append(group_copy)
                    group_id = _text(_first(group, "uuid", "id", "defectGroupUuid"))
                    group_state = _state(_first(group, "status", "state"))
                    if group_state == "UNKNOWN":
                        group_errors += 1
                        continue
                    if not group_id or group_state != "ACTIVE":
                        continue
                    finding_response = client.get(
                        "/v1/findings",
                        params={"defectGroupUuid": group_id, "gitRepo": repository_id},
                    )
                    if finding_response.status_code in {401, 403, 404}:
                        finding_errors += 1
                        continue
                    finding_response.raise_for_status()
                    for finding in _rows(finding_response.json(), "data", "findings"):
                        finding_copy = dict(finding)
                        finding_copy["groupUuid"] = group_id
                        finding_copy["scanUuid"] = scan_id
                        finding_rows.append(finding_copy)
            return {
                "schema_version": APPSEC_ADAPTER_VERSION,
                "repository_id": repository_id,
                "scans": scans,
                "groups": groups,
                "findings": finding_rows,
                "group_errors": group_errors,
                "finding_errors": finding_errors,
            }


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _rows(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise AppSecPayloadError("SourceCraft AppSec response must be an object")
    value: Any = payload
    for key in keys:
        if isinstance(value, Mapping) and key in value:
            value = value[key]
            break
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise AppSecPayloadError("SourceCraft AppSec response data must be an array")
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _state(value: Any) -> str:
    if isinstance(value, bool):
        return "ACTIVE" if value else "FIXED"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if int(value) == 0:
            return "ACTIVE"
        if int(value) == 9:
            return "FIXED"
        return "UNKNOWN"
    normalized = str(value or "").strip().upper().replace("-", "_")
    if normalized in {"0", "ACTIVE", "OPEN", "NEW", "UNRESOLVED"}:
        return "ACTIVE"
    if normalized in {"9", "FIXED", "RESOLVED", "CLOSED", "INACTIVE"}:
        return "FIXED"
    return "UNKNOWN"


def _severity(value: Any) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized in {"critical", "fatal", "blocker"}:
        return "critical"
    if normalized in {"high", "major"}:
        return "high"
    if normalized in {"medium", "moderate", "normal"}:
        return "medium"
    if normalized in {"low", "minor"}:
        return "low"
    return "unknown"


def _payload_from_inventory(context: AnalyzerContext) -> Mapping[str, Any] | None:
    for key in ("sourcecraft_appsec", "appsec_facts", "appsec"):
        value = context.inventory.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _repository_id(context: AnalyzerContext) -> str | None:
    inventory = context.inventory
    for key in ("appsec_repository_id", "sourcecraft_repository_id", "repository_id", "git_repo", "id"):
        value = inventory.get(key)
        if value:
            return str(value)
    for key in ("sourcecraft_metadata", "repository"):
        nested = inventory.get(key)
        if isinstance(nested, Mapping):
            value = nested.get("id") or nested.get("repository_id")
            if value:
                return str(value)
    return None


def _finding_from_row(row: Mapping[str, Any], index: int, *, group: Mapping[str, Any] | None = None) -> AppSecFindingFact:
    group = group or {}
    finding_id = _text(_first(row, "uuid", "id", "findingUuid", "findingId")) or f"finding-{index}"
    group_id = _text(_first(row, "groupUuid", "defectGroupUuid")) or _text(_first(group, "uuid", "id"))
    scan_id = _text(_first(row, "scanUuid")) or _text(_first(group, "scanUuid"))
    file_name = _text(_first(row, "fileName", "file", "path", "component"))
    line = _number(_first(row, "line", "lineNumber", "startLine"))
    return AppSecFindingFact(
        finding_id=finding_id,
        group_id=group_id,
        scan_id=scan_id,
        engine=_text(_first(row, "engine")) or _text(_first(group, "engine")),
        engine_type=_text(_first(row, "engineType")) or _text(_first(group, "engineType")),
        rule=_text(_first(row, "rule", "ruleName")) or _text(_first(group, "rule", "ruleName")),
        severity=_severity(_first(row, "severity", "severityObserved") or _first(group, "severity", "severityObserved")),
        state=_state(_first(row, "status", "state") or _first(group, "status", "state")),
        file=file_name,
        line=line,
        message=_text(_first(row, "message", "description")),
        deep_link=_text(_first(row, "url", "webUrl", "deepLink")),
        json_pointer=f"/findings/{index}",
    )


def normalize_appsec_payload(payload: Mapping[str, Any], repository_id: str | None = None) -> AppSecFacts:
    """Normalize REST or deterministic fixture payloads without provider objects."""
    status_value = str(payload.get("status") or "").strip().upper()
    if status_value in {"UNAVAILABLE", "ERROR"}:
        return AppSecFacts(
            status=AppSecDataStatus(status_value),
            repository_id=repository_id,
            scans_count=0,
            groups_count=0,
            findings=(),
            coverage=0.0,
            confidence=0.0,
            failure_kind=_text(payload.get("failure_kind") or payload.get("reason")),
        )
    scans = _rows(payload, "scans", "data") if payload.get("scans") is not None else []
    groups = _rows(payload, "groups", "data") if payload.get("groups") is not None else []
    raw_findings = payload.get("findings")
    if raw_findings is None:
        raw_findings = []
    if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes, bytearray)):
        raise AppSecPayloadError("AppSec findings must be an array")
    group_by_id = {
        str(_first(group, "uuid", "id")): group
        for group in groups
        if _first(group, "uuid", "id") is not None
    }
    findings: list[AppSecFindingFact] = []
    seen: set[str] = set()
    for index, row in enumerate(raw_findings):
        if not isinstance(row, Mapping):
            continue
        fact = _finding_from_row(row, index, group=group_by_id.get(str(_first(row, "groupUuid", "defectGroupUuid"))))
        if fact.finding_id in seen:
            continue
        seen.add(fact.finding_id)
        findings.append(fact)
    group_errors = int(payload.get("group_errors") or 0)
    finding_errors = int(payload.get("finding_errors") or 0)
    unknown_groups = sum(
        _state(_first(group, "status", "state")) == "UNKNOWN"
        for group in groups
    )
    unavailable_groups = group_errors + finding_errors + unknown_groups
    total_groups = len(groups) + unavailable_groups
    coverage = 1.0 if total_groups == 0 else len(groups) / total_groups
    status = AppSecDataStatus.PARTIAL if unavailable_groups else AppSecDataStatus.MEASURED
    if status_value == "PARTIAL":
        status = AppSecDataStatus.PARTIAL
    return AppSecFacts(
        status=status,
        repository_id=repository_id or _text(payload.get("repository_id")),
        scans_count=len(scans),
        groups_count=len(groups),
        findings=tuple(findings),
        coverage=coverage,
        confidence=coverage,
        failure_kind=None,
        groups_with_unavailable_findings=unavailable_groups,
        diagnostics={
            "unknown_severity_count": sum(item.severity == "unknown" for item in findings),
            "status_mapping": "provider_numeric_0_active_9_fixed_string_fallback_unknown",
        },
    )


class SourceCraftAppSecAdapter:
    """Collect and normalize SourceCraft AppSec data for one repository."""

    def __init__(self, transport: AppSecTransport | None = None) -> None:
        self.transport = transport

    def collect(self, context: AnalyzerContext) -> AppSecFacts:
        repository_id = _repository_id(context)
        fixture = _payload_from_inventory(context)
        if fixture is not None:
            return normalize_appsec_payload(fixture, repository_id=repository_id)
        if not repository_id:
            return AppSecFacts(AppSecDataStatus.UNAVAILABLE, None, 0, 0, (), 0.0, 0.0, failure_kind="repository_id_missing")
        transport = self.transport or SourceCraftAppSecHTTPTransport()
        try:
            payload = transport.fetch({"git_repo": repository_id})
            return normalize_appsec_payload(payload, repository_id=repository_id)
        except AppSecUnavailableError as exc:
            log.warning("appsec_unavailable", repo_id=context.repo_id, reason=str(exc))
            return AppSecFacts(AppSecDataStatus.UNAVAILABLE, repository_id, 0, 0, (), 0.0, 0.0, failure_kind=type(exc).__name__)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            log.error("appsec_collection_failed", repo_id=context.repo_id, failure_kind=type(exc).__name__)
            return AppSecFacts(AppSecDataStatus.ERROR, repository_id, 0, 0, (), 0.0, 0.0, failure_kind=type(exc).__name__)


def finding_evidence(context: AnalyzerContext, facts: AppSecFacts, item: AppSecFindingFact) -> EvidenceRef:
    return EvidenceRef(
        source="sourcecraft-appsec",
        source_commit=facts.source_version,
        path=item.deep_link or item.file,
        line_start=item.line,
        json_pointer=item.json_pointer,
        collected_at=context.as_of_ts,
        confidence=facts.confidence,
        redaction="partial",
    )


def finding_to_contract(context: AnalyzerContext, facts: AppSecFacts, item: AppSecFindingFact) -> Finding:
    evidence = finding_evidence(context, facts, item)
    return Finding(
        id=f"sourcecraft.appsec:{item.finding_id}",
        analyzer_id="sourcecraft.appsec",
        subject=f"{item.engine or 'appsec'}:{item.rule or item.finding_id}",
        dimension="security",
        severity=item.severity if item.severity in {"info", "low", "medium", "high", "critical"} else "medium",
        confidence=facts.confidence,
        reason=f"Active {item.severity} AppSec finding{f' in {item.file}' if item.file else ''}.",
        location=FindingLocation(path=item.file, line_start=item.line) if item.file or item.line else None,
        evidence_refs=(evidence,),
        remediation="Review and remediate the active SourceCraft AppSec finding.",
    )


def stable_facts_ref(facts: AppSecFacts) -> str:
    payload = json.dumps(facts.summary(), sort_keys=True, default=str, separators=(",", ":"))
    return "sourcecraft-appsec://" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "APPSEC_ADAPTER_VERSION",
    "APPSEC_SOURCE_COMMIT",
    "AppSecDataStatus",
    "AppSecFacts",
    "AppSecFindingFact",
    "AppSecPayloadError",
    "AppSecTransport",
    "SourceCraftAppSecAdapter",
    "SourceCraftAppSecHTTPTransport",
    "finding_evidence",
    "finding_to_contract",
    "normalize_appsec_payload",
    "stable_facts_ref",
]
