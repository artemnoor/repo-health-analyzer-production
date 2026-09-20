"""SonarQube Web API adapter for Code Health.

The adapter accepts either a canonical ``sonarqube_code_health`` snapshot or an
injected transport.  It normalizes only Code Smell/Bug quality observations;
Security findings remain owned by SourceCraft AppSec.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any, Protocol

import structlog

from .code_health_facts import (
    CodeHealthEvidenceFact,
    CodeHealthPolicy,
    CodeHealthStatus,
    SonarFacts,
    SonarIssueFact,
    stable_digest,
)
from .contracts import AnalyzerContext

log = structlog.get_logger("health.code_health.sonarqube")

SONAR_ADAPTER_VERSION = "sonarqube-adapter-v1"
SONAR_SCHEMA_VERSION = "repowise-sonarqube-code-health-v1"


class SonarQubePayloadError(ValueError):
    """Raised when a Sonar snapshot violates the normalized input contract."""


class SonarQubeTransport(Protocol):
    def fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any] | str: ...


class SonarQubeHTTPTransport:
    """Small official Web API client used by the configured production edge.

    The transport is intentionally separate from normalization: it performs
    only bounded API calls and returns the adapter's canonical snapshot shape.
    Tokens are accepted in memory, sent as Basic auth, and never included in
    diagnostics or logs.
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0, page_size: int = 500) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = max(1.0, timeout)
        self.page_size = max(1, min(500, page_size))

    def fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is in project core
            raise RuntimeError("httpx is required for SonarQube Web API transport") from exc
        project_key = str(request.get("project_key") or "").strip()
        if not project_key:
            raise ValueError("sonarqube project_key is required")
        metric_keys = ",".join(
            (
                "sqale_rating",
                "sqale_index",
                "code_smells",
                "cognitive_complexity",
                "complexity",
                "duplicated_lines_density",
                "duplicated_lines",
                "ncloc",
                "bugs",
                "coverage",
            )
        )
        auth = (self.token, "")
        with httpx.Client(base_url=self.base_url, auth=auth, timeout=self.timeout, follow_redirects=True) as client:
            component_response = client.get(
                "/api/measures/component",
                params={"component": project_key, "metricKeys": metric_keys},
            )
            component_response.raise_for_status()
            component_payload = component_response.json()
            server_response = client.get("/api/server/version")
            server_version = server_response.text.strip() if server_response.is_success else None
            root_component = component_payload.get("component") if isinstance(component_payload, Mapping) else {}
            measures = root_component.get("measures", []) if isinstance(root_component, Mapping) else []

            issues: list[Mapping[str, Any]] = []
            page = 1
            pagination_complete = True
            while True:
                issue_response = client.get(
                    "/api/issues/search",
                    params={
                        "componentKeys": project_key,
                        "types": "CODE_SMELL,BUG",
                        "ps": self.page_size,
                        "p": page,
                    },
                )
                issue_response.raise_for_status()
                issue_payload = issue_response.json()
                page_rows = issue_payload.get("issues", []) if isinstance(issue_payload, Mapping) else []
                if not isinstance(page_rows, list):
                    raise ValueError("SonarQube issues response has invalid issues field")
                issues.extend(row for row in page_rows if isinstance(row, Mapping))
                paging = issue_payload.get("paging", {}) if isinstance(issue_payload, Mapping) else {}
                total = int(paging.get("total", len(issues))) if isinstance(paging, Mapping) else len(issues)
                if len(issues) >= total or not page_rows:
                    break
                page += 1
                if page > 1000:
                    pagination_complete = False
                    break

            tree_response = client.get(
                "/api/components/tree",
                params={"component": project_key, "qualifiers": "FIL", "ps": self.page_size, "p": 1},
            )
            tree_response.raise_for_status()
            tree_payload = tree_response.json()
            components = tree_payload.get("components", []) if isinstance(tree_payload, Mapping) else []
            analysis_id = request.get("analysis_id")
            analysis_response = client.get(
                "/api/project_analyses/search",
                params={"project": project_key, "ps": 1},
            )
            if analysis_response.is_success:
                analysis_payload = analysis_response.json()
                analyses = analysis_payload.get("analyses", []) if isinstance(analysis_payload, Mapping) else []
                if analyses and isinstance(analyses[0], Mapping):
                    analysis_id = analysis_id or analyses[0].get("key")
            return {
                "schema_version": SONAR_SCHEMA_VERSION,
                "status": "SUCCESS",
                "project_key": project_key,
                "analysis_id": analysis_id,
                "server_version": request.get("server_version") or server_version,
                "scanner_version": request.get("scanner_version"),
                "measures": measures,
                "components": components,
                "issues": issues,
                "pages_fetched": page,
                "pagination_complete": pagination_complete,
                "coverage_provenance": request.get("coverage_provenance") or {},
            }


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return value if isinstance(value, Sequence) else None


def _text(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _effort_minutes(value: object) -> float | None:
    number = _number(value)
    if number is not None:
        return number
    match = re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
    return float(match.group(1)) if match else None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _status(value: object, *, has_content: bool) -> CodeHealthStatus:
    normalized = str(value or "").strip().upper().replace("-", "_")
    if normalized in {"ERROR", "FAILED", "FAILURE"}:
        return CodeHealthStatus.ERROR
    if normalized in {"PARTIAL", "INCOMPLETE", "TIMEOUT"}:
        return CodeHealthStatus.PARTIAL
    if normalized in {"UNAVAILABLE", "MISSING", "NOT_FOUND"}:
        return CodeHealthStatus.UNAVAILABLE
    if normalized in {"NOT_APPLICABLE", "N_A"}:
        return CodeHealthStatus.NOT_APPLICABLE
    if normalized in {"MEASURED", "SUCCESS", "COMPLETED", "OK"}:
        return CodeHealthStatus.MEASURED
    return CodeHealthStatus.MEASURED if has_content else CodeHealthStatus.NOT_APPLICABLE


def _payload(snapshot: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            raise SonarQubePayloadError("Sonar snapshot is not valid JSON") from exc
    if not isinstance(snapshot, Mapping):
        raise SonarQubePayloadError("Sonar snapshot must be a JSON object")
    return snapshot


def _raw_measures(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("measures")
    if isinstance(raw, Mapping):
        result: list[Mapping[str, Any]] = []
        for metric, value in raw.items():
            if isinstance(value, Mapping):
                result.append({**dict(value), "metric": metric})
            else:
                result.append({"metric": metric, "value": value})
        return result
    sequence = _sequence(raw)
    if sequence is None:
        component = _mapping(payload.get("component"))
        sequence = _sequence(component.get("measures")) if component else None
    return [item for item in (sequence or ()) if isinstance(item, Mapping)]


def _component_rows(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = payload.get("components")
    if raw is None:
        raw = payload.get("component_tree")
    sequence = _sequence(raw)
    if sequence is None:
        component = _mapping(payload.get("component"))
        sequence = (component,) if component else ()
    rows: list[Mapping[str, Any]] = []
    for item in sequence:
        mapping = _mapping(item)
        if mapping is None:
            continue
        measures: dict[str, float | str] = {}
        for measure in _raw_measures(mapping):
            metric = _text(_first(measure, "metric", "key"))
            value = _first(measure, "value", "bestValue")
            if metric and value is not None:
                measures[metric] = value if isinstance(value, str) else (_number(value) if _number(value) is not None else str(value))
        path = _text(_first(mapping, "path", "key", "name"))
        if path:
            rows.append({"path": str(PurePosixPath(path.replace("\\", "/"))), "measures": measures})
        if len(rows) >= 500:
            break
    return tuple(rows)


def _issue_facts(payload: Mapping[str, Any], max_findings: int) -> tuple[tuple[SonarIssueFact, ...], int]:
    raw = payload.get("issues")
    if isinstance(raw, Mapping):
        raw = raw.get("issues")
    sequence = _sequence(raw)
    if sequence is None:
        return (), 0
    issues: list[SonarIssueFact] = []
    ignored_security = 0
    for item in sequence:
        row = _mapping(item)
        if row is None:
            continue
        issue_type = str(_first(row, "type", "issueType") or "").upper()
        if issue_type not in {"CODE_SMELL", "BUG"}:
            if issue_type in {"VULNERABILITY", "SECURITY_HOTSPOT"}:
                ignored_security += 1
            continue
        text_range = _mapping(row.get("textRange")) or _mapping(row.get("text_range")) or {}
        line = _first(row, "line") or _first(text_range, "startLine", "start_line")
        line_number = int(line) if isinstance(line, (int, float, str)) and str(line).isdigit() else None
        component = _text(_first(row, "component", "componentKey"))
        path = component.split(":", 1)[-1] if component else None
        issues.append(
            SonarIssueFact(
                issue_id=_text(_first(row, "key", "id")) or f"issue-{len(issues)}",
                rule=_text(_first(row, "rule", "ruleKey")),
                issue_type=issue_type,
                severity=_text(_first(row, "severity")),
                component=component,
                path=path,
                line=line_number,
                effort_minutes=_effort_minutes(_first(row, "effort", "debt")),
                message=_text(_first(row, "message")),
            )
        )
        if len(issues) >= max_findings:
            break
    return tuple(issues), ignored_security


class SonarQubeAdapter:
    """Normalize one SonarQube snapshot without exposing raw API objects."""

    def collect(
        self,
        context: AnalyzerContext,
        policy: CodeHealthPolicy,
        *,
        snapshot: Mapping[str, Any] | str | None = None,
        transport: SonarQubeTransport | None = None,
    ) -> SonarFacts:
        if snapshot is None and transport is None:
            return SonarFacts(
                status=CodeHealthStatus.UNAVAILABLE,
                confidence=0.0,
                diagnostics={"failure_kind": "snapshot_missing", "process_invoked": False},
            )
        try:
            if snapshot is None and transport is not None:
                snapshot = transport.fetch(
                    {
                        "project_key": context.inventory.get("sonarqube_project_key"),
                        "analysis_id": context.inventory.get("sonarqube_analysis_id"),
                        "scanner_version": context.inventory.get("sonarqube_scanner_version"),
                        "coverage_provenance": context.inventory.get("sonarqube_coverage_provenance") or {},
                    }
                )
            payload = _payload(snapshot or {})
            measures: dict[str, float | str] = {}
            evidence: list[CodeHealthEvidenceFact] = []
            coverage_provenance = _mapping(payload.get("coverage_provenance")) or {}
            aliases = {alias: normalized for normalized, values in policy.sonar_metric_aliases.items() for alias in values}
            for index, row in enumerate(_raw_measures(payload)):
                metric = _text(_first(row, "metric", "key"))
                value = _first(row, "value", "bestValue")
                if not metric or value is None:
                    continue
                normalized = aliases.get(metric, metric)
                if normalized == "coverage" and not (
                    coverage_provenance.get("report_path")
                    or coverage_provenance.get("report_type")
                    or coverage_provenance.get("coverage_report")
                ):
                    continue
                number = _number(value)
                measures[normalized] = number if number is not None else str(value)
                evidence.append(
                    CodeHealthEvidenceFact(
                        source="sonarqube",
                        json_pointer=f"/measures/{index}",
                        subject=normalized,
                        value=measures[normalized],
                    )
                )
            issues, ignored_security = _issue_facts(payload, policy.max_findings)
            if "remediation_effort" not in measures:
                effort = sum(item.effort_minutes or 0.0 for item in issues)
                if effort:
                    measures["remediation_effort"] = effort
            status = _status(_first(payload, "collection_status", "status"), has_content=bool(measures or issues or payload.get("component") is not None))
            coverage_measure = measures.get("coverage")
            coverage_available = bool(
                coverage_provenance.get("report_path")
                or coverage_provenance.get("report_type")
                or coverage_provenance.get("coverage_report")
            )
            coverage_status = CodeHealthStatus.MEASURED if coverage_available and coverage_measure is not None else CodeHealthStatus.NOT_APPLICABLE
            pages = int(_first(payload, "pages_fetched", "page_count") or 1)
            pagination_complete = payload.get("pagination_complete")
            if pagination_complete is False and status is CodeHealthStatus.MEASURED:
                status = CodeHealthStatus.PARTIAL
            completeness = 1.0 if pagination_complete is not False else 0.5
            confidence = completeness if status in {CodeHealthStatus.MEASURED, CodeHealthStatus.PARTIAL} else 0.0
            diagnostics = {
                "schema_version": _text(payload.get("schema_version")) or SONAR_SCHEMA_VERSION,
                "ignored_security_issue_count": ignored_security,
                "metric_count": len(measures),
                "issue_count": len(issues),
                "component_count": len(_component_rows(payload)),
                "coverage_provenance_present": coverage_available,
                "pages_fetched": pages,
                "pagination_complete": pagination_complete,
            }
            return SonarFacts(
                status=status,
                project_key=_text(_first(payload, "project_key", "projectKey")),
                analysis_id=_text(_first(payload, "analysis_id", "analysisId")),
                server_version=_text(_first(payload, "server_version", "serverVersion")),
                scanner_version=_text(_first(payload, "scanner_version", "scannerVersion")),
                measures=measures,
                components=_component_rows(payload),
                issues=issues,
                coverage_status=coverage_status,
                coverage_provenance=coverage_provenance,
                source_snapshot_digest=_text(payload.get("source_snapshot_digest")) or stable_digest(payload),
                pages_fetched=pages,
                pagination_complete=pagination_complete if isinstance(pagination_complete, bool) else None,
                coverage=completeness,
                confidence=confidence,
                diagnostics=diagnostics,
                evidence=tuple(evidence),
            )
        except Exception as exc:
            log.error("sonarqube_snapshot_invalid", repo_id=context.repo_id, error_type=type(exc).__name__)
            return SonarFacts(
                status=CodeHealthStatus.ERROR,
                confidence=0.0,
                diagnostics={"failure_kind": "malformed_snapshot", "error_type": type(exc).__name__},
            )


__all__ = [
    "SONAR_ADAPTER_VERSION",
    "SONAR_SCHEMA_VERSION",
    "SonarQubeAdapter",
    "SonarQubeHTTPTransport",
    "SonarQubePayloadError",
    "SonarQubeTransport",
]
