"""Thin Forge/RepoCrunch adapter.

RepoCrunch remains the owner of the GitHub client, retry, ETag and extractor
algorithms. This module only supplies a RepoWise context, preserves raw facts
and maps its Pydantic result into the shared analyzer envelope.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    Limitation,
    MetricValue,
)
from .process import workspace_root

log = structlog.get_logger("forge.collect")

REPOCRUNCH_COMMIT = "12938318a6bd59e30a431ab2582baff5d8673eca"
FORGE_METADATA_ID = "forge.metadata"
FORGE_COMMUNITY_ID = "forge.community"

FORGE_METADATA_DEFINITION = AnalyzerDefinition(
    id=FORGE_METADATA_ID,
    version="pinned",
    category="forge-metadata",
    dimensions=("documentation", "repository-hygiene", "architecture"),
    requires=("forge:github",),
    phase=50,
    cost=35,
    timeout=90,
    cache_policy="read_write",
    source_commit=REPOCRUNCH_COMMIT,
    enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
)
FORGE_COMMUNITY_DEFINITION = AnalyzerDefinition(
    id=FORGE_COMMUNITY_ID,
    version="pinned",
    category="forge-community",
    dimensions=("community", "issues", "maintenance"),
    requires=("forge:github",),
    phase=50,
    cost=40,
    timeout=90,
    cache_policy="read_write",
    source_commit=REPOCRUNCH_COMMIT,
    enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
)


@dataclass(frozen=True)
class RawFact:
    """Immutable raw event boundary; source IDs are never rewritten."""

    source: str
    repo_id: str
    event_type: str
    stable_event_id: str
    payload: dict[str, Any]
    updated_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    cursor: str | None = None
    permission_state: str = "granted"
    source_version: str = REPOCRUNCH_COMMIT


@dataclass(frozen=True)
class ForgeCollection:
    facts: tuple[RawFact, ...] = ()
    cursor: str | None = None
    permission_state: str = "granted"
    warnings: tuple[str, ...] = ()
    rate_remaining: int | None = None
    etag_hits: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


def _repocrunch_source() -> Path:
    source = workspace_root() / "vendor" / "repocrunch" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def _utc(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _payload_ref(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"forge://repocrunch/{hashlib.sha256(raw.encode()).hexdigest()}"


def _stable_id(item: dict[str, Any], event_type: str, index: int) -> str:
    for key in ("id", "node_id", "sha", "number", "url", "html_url", "event_id"):
        if item.get(key) not in (None, ""):
            return str(item[key])
    raw = json.dumps(item, sort_keys=True, default=str, separators=(",", ":"))
    return f"{event_type}:{hashlib.sha256(f'{index}:{raw}'.encode()).hexdigest()[:20]}"


def _event_items(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    raw_events = payload.get("events")
    if isinstance(raw_events, list):
        for item in raw_events:
            if isinstance(item, dict):
                events.append((str(item.get("event_type") or item.get("type") or "event"), item))
    for event_type in ("commits", "issues", "pull_requests", "reviews", "releases", "dependencies", "sbom", "ci_runs", "messages"):
        items = payload.get(event_type)
        if isinstance(items, list):
            normalized_type = event_type.removesuffix("s")
            events.extend((normalized_type, item) for item in items if isinstance(item, dict))
    return events


class ForgeAdapter:
    """Calls the copied RepoCrunch orchestrator and retains its raw boundary."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], ForgeCollection] = {}

    def collect(self, context: AnalyzerContext, *, window: str = "all", cursor: str | None = None) -> ForgeCollection:
        key = (context.repo_id, context.head_sha)
        if key in self._cache:
            return self._cache[key]

        payload = context.inventory.get("forge_payload")
        if not isinstance(payload, dict):
            payload = context.inventory.get("forge_payloads")
        warnings: list[str] = []
        if not isinstance(payload, dict):
            try:
                _repocrunch_source()
                from repocrunch.analyzer import analyze_repo

                repo_input = str(context.inventory.get("forge_repo") or context.repo_id)
                token = context.inventory.get("forge_token")
                analysis = asyncio.run(analyze_repo(repo_input, token=str(token) if token else None))
                payload = {"repo_analysis": analysis.model_dump(mode="json"), "source": "repocrunch"}
            except (ImportError, RuntimeError, ValueError, OSError) as exc:
                warnings.append(f"RepoCrunch collection unavailable: {type(exc).__name__}")
                payload = {}

        permission_state = str(payload.get("permission_state") or "granted")
        status_code = payload.get("status_code")
        if status_code in {401, 403, 404, "401", "403", "404"}:
            permission_state = "unknown"
            warnings.append(f"Forge source returned {status_code}; affected facts are unknown")
        warnings.extend(str(item) for item in payload.get("warnings", []) if item)
        rate_remaining = payload.get("rate_remaining")
        try:
            rate_remaining = int(rate_remaining) if rate_remaining is not None else None
        except (TypeError, ValueError):
            rate_remaining = None
        if rate_remaining is not None and rate_remaining < 5:
            warnings.append("Forge rate budget is nearly exhausted")

        facts: list[RawFact] = []
        source = str(payload.get("source") or "repocrunch")
        source_version = str(payload.get("source_version") or REPOCRUNCH_COMMIT)
        for index, (event_type, item) in enumerate(_event_items(payload)):
            facts.append(
                RawFact(
                    source=source,
                    repo_id=context.repo_id,
                    event_type=event_type,
                    stable_event_id=_stable_id(item, event_type, index),
                    payload=dict(item),
                    updated_at=_utc(item.get("updated_at") or item.get("updatedAt") or item.get("created_at")),
                    window_start=_utc(payload.get("window_start")),
                    window_end=_utc(payload.get("window_end")) or context.as_of_ts,
                    cursor=str(payload.get("cursor") or cursor) if payload.get("cursor") or cursor else None,
                    permission_state=permission_state,
                    source_version=source_version,
                )
            )
        if isinstance(payload.get("repo_analysis"), dict):
            facts.append(
                RawFact(
                    source=source,
                    repo_id=context.repo_id,
                    event_type="repository",
                    stable_event_id=context.repo_id,
                    payload=dict(payload["repo_analysis"]),
                    updated_at=context.as_of_ts,
                    window_end=context.as_of_ts,
                    cursor=str(payload.get("cursor")) if payload.get("cursor") else cursor,
                    permission_state=permission_state,
                    source_version=source_version,
                )
            )
        collection = ForgeCollection(
            facts=tuple(facts),
            cursor=str(payload.get("cursor") or cursor) if payload.get("cursor") or cursor else None,
            permission_state=permission_state,
            warnings=tuple(dict.fromkeys(warnings)),
            rate_remaining=rate_remaining,
            etag_hits=int(payload.get("etag_hits") or 0),
            payload=dict(payload),
        )
        self._cache[key] = collection
        log.info(
            "collection_finished repo_id=%s window=%s facts=%d permission=%s etag_hits=%d",
            context.repo_id,
            window,
            len(collection.facts),
            permission_state,
            collection.etag_hits,
        )
        return collection

    @staticmethod
    def _evidence(context: AnalyzerContext, *, pointer: str, path: str | None = None) -> EvidenceRef:
        return EvidenceRef(
            source="forge.repocrunch",
            source_commit=REPOCRUNCH_COMMIT,
            path=path,
            json_pointer=pointer,
            collected_at=context.as_of_ts,
        )

    def result(self, context: AnalyzerContext, *, focus: str) -> AnalyzerResult:
        collection = self.collect(context)
        analysis_fact = next((fact for fact in collection.facts if fact.event_type == "repository"), None)
        analysis = analysis_fact.payload if analysis_fact else {}
        metrics: list[MetricValue] = []
        evidence: list[EvidenceRef] = []

        def add(name: str, value: object, pointer: str, *, unit: str | None = None, denominator: int | None = None, dimension: str | None = None) -> None:
            ref = self._evidence(context, pointer=pointer)
            evidence.append(ref)
            metrics.append(MetricValue(name=name, dimension=dimension or ("docs" if focus == "metadata" else "community"), value=value, unit=unit, denominator=denominator, evidence_refs=(ref,)))

        if focus == "metadata":
            summary = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
            architecture = analysis.get("architecture") if isinstance(analysis.get("architecture"), dict) else {}
            tech_stack = analysis.get("tech_stack") if isinstance(analysis.get("tech_stack"), dict) else {}
            for key, unit in (("stars", "stars"), ("forks", "forks"), ("watchers", "watchers"), ("age_days", "days")):
                if key in summary:
                    add(f"forge:{key}", summary[key], f"/repo_analysis/summary/{key}", unit=unit)
            for key in ("primary_language", "license"):
                if summary.get(key):
                    add(f"forge:{key}", summary[key], f"/repo_analysis/summary/{key}")
            for key in ("monorepo", "docker", "has_tests"):
                if key in architecture:
                    add(f"forge:architecture:{key}", architecture[key], f"/repo_analysis/architecture/{key}")
            if tech_stack.get("package_manager"):
                add("forge:package_manager", tech_stack["package_manager"], "/repo_analysis/tech_stack/package_manager")
        else:
            health = analysis.get("health") if isinstance(analysis.get("health"), dict) else {}
            security = analysis.get("security") if isinstance(analysis.get("security"), dict) else {}
            for key, unit in (("open_issues", "issues"), ("open_prs", "pull_requests"), ("contributors", "contributors")):
                if key in health:
                    add(f"forge:{key}", health[key], f"/repo_analysis/health/{key}", unit=unit)
            for key in ("commit_frequency", "maintenance_status"):
                if health.get(key):
                    add(f"forge:{key}", health[key], f"/repo_analysis/health/{key}")
            for key in ("branch_protection", "security_policy", "dependabot_enabled", "has_env_file"):
                if key in security:
                    add(
                        f"forge:security:{key}",
                        security[key],
                        f"/repo_analysis/security/{key}",
                        dimension="security" if key in {"security_policy", "dependabot_enabled", "has_env_file"} else "delivery",
                    )
            counts: dict[str, int] = {}
            for fact in collection.facts:
                counts[fact.event_type] = counts.get(fact.event_type, 0) + 1
            for event_type, count in sorted(counts.items()):
                add(f"forge:events:{event_type}", count, f"/events/{event_type}", denominator=count)

        findings = tuple(
            Finding(
                id=f"{FORGE_METADATA_ID if focus == 'metadata' else FORGE_COMMUNITY_ID}:warning:{index}",
                analyzer_id=FORGE_METADATA_ID if focus == "metadata" else FORGE_COMMUNITY_ID,
                subject="forge-source",
                dimension="repository-hygiene" if focus == "metadata" else "community",
                severity="medium",
                confidence=1.0,
                reason=warning,
                evidence_refs=(self._evidence(context, pointer="/warnings"),),
                remediation="Resolve the forge collection warning or provide the missing repository metadata capability.",
            )
            for index, warning in enumerate(collection.warnings)
        )
        analyzer_id = FORGE_METADATA_ID if focus == "metadata" else FORGE_COMMUNITY_ID
        definition = FORGE_METADATA_DEFINITION if focus == "metadata" else FORGE_COMMUNITY_DEFINITION
        status = AnalyzerStatus.INCONCLUSIVE if not metrics and not collection.facts else AnalyzerStatus.WARN if findings or collection.permission_state == "unknown" else AnalyzerStatus.PASS
        limitation_items: list[Limitation] = []
        if not metrics:
            limitation_items.append(Limitation(reason="Forge returned no usable facts", kind="insufficient_denominator"))
        if collection.permission_state == "unknown":
            limitation_items.append(Limitation(reason="Forge permission state is unknown; community metrics may be incomplete", kind="missing_capability"))
        limitation = tuple(limitation_items)
        return AnalyzerResult(
            analyzer_id=analyzer_id,
            analyzer_version="pinned",
            status=status,
            metrics=tuple(metrics),
            findings=findings,
            evidence=tuple({ref.model_dump_json(): ref for ref in evidence}.values()),
            limitations=limitation,
            available_weight=float(len(metrics)),
            total_weight=float(len(metrics)),
            raw_payload_ref=_payload_ref(collection.payload),
            source_versions={"repocrunch": REPOCRUNCH_COMMIT},
            diagnostics={
                "permission_state": collection.permission_state,
                "cursor": collection.cursor,
                "rate_remaining": collection.rate_remaining,
                "etag_hits": collection.etag_hits,
                "raw_fact_count": len(collection.facts),
                "stable_event_ids": [fact.stable_event_id for fact in collection.facts],
                "window_end": context.as_of_ts.isoformat(),
                "definition": definition.id,
            },
        )

    def run_metadata(self, context: AnalyzerContext) -> AnalyzerResult:
        return self.result(context, focus="metadata")

    def run_community(self, context: AnalyzerContext) -> AnalyzerResult:
        return self.result(context, focus="community")


_DEFAULT_FORGE_ADAPTER: ForgeAdapter | None = None


def _adapter() -> ForgeAdapter:
    global _DEFAULT_FORGE_ADAPTER
    if _DEFAULT_FORGE_ADAPTER is None:
        _DEFAULT_FORGE_ADAPTER = ForgeAdapter()
    return _DEFAULT_FORGE_ADAPTER


def forge_metadata_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return _adapter().run_metadata(context)


def forge_community_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return _adapter().run_community(context)


def register_forge_adapters(registry: Any) -> None:
    for definition, factory in (
        (FORGE_METADATA_DEFINITION, forge_metadata_adapter),
        (FORGE_COMMUNITY_DEFINITION, forge_community_adapter),
    ):
        if definition.id not in registry.ids():
            registry.register(definition, factory)


__all__ = [
    "FORGE_COMMUNITY_DEFINITION",
    "FORGE_COMMUNITY_ID",
    "FORGE_METADATA_DEFINITION",
    "FORGE_METADATA_ID",
    "ForgeAdapter",
    "ForgeCollection",
    "RawFact",
    "forge_community_adapter",
    "forge_metadata_adapter",
    "register_forge_adapters",
]
