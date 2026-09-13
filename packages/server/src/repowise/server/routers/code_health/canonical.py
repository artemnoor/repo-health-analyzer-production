"""Canonical persisted health projection.

This module is deliberately a read model. It does not call a detector, load
legacy per-file health rows, or invoke a score function. REST and MCP import
the same builder so a dashboard request and an agent request cannot silently
disagree about score, evidence or limitations.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from repowise.core.persistence.models import (
    HealthAggregate,
    HealthFindingEvidence,
    HealthMetricValue,
    HealthRecommendation,
    HealthScoreProjection,
    HealthSourceRun,
    RepositoryHealthSnapshot,
)
from repowise.server.schemas.code_health import CanonicalHealthReport

_WINDOW_RE = re.compile(r"^(?P<count>\d+)\s*(?P<unit>[dhm])$", re.IGNORECASE)
log = logging.getLogger("api.health")


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        loaded = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return loaded


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat()
    return str(value)


def _column_dict(row: Any, columns: Iterable[Any]) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in columns}


def _parse_window(window: str | None) -> datetime | None:
    """Turn a bounded query window into its UTC lower bound.

    Accepted values are ``7d``, ``12h``, ``30m`` and an ISO timestamp/date.
    The parser is shared by all rows, while the stored window boundaries remain
    authoritative for metrics and recommendations.
    """
    if not window:
        return None
    match = _WINDOW_RE.fullmatch(window.strip())
    if match:
        count = int(match.group("count"))
        unit = match.group("unit").lower()
        seconds = count * {"d": 86400, "h": 3600, "m": 60}[unit]
        return datetime.now(UTC) - timedelta(seconds=seconds)
    try:
        parsed = datetime.fromisoformat(window.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("window must be an ISO-8601 timestamp or a duration such as 90d") from exc
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _evidence_ref(row: Any) -> dict[str, Any]:
    return {
        "source": row.source,
        "source_commit": row.source_commit,
        "tool_version": row.tool_version,
        "path": row.path,
        "line_start": row.line_start,
        "line_end": row.line_end,
        "json_pointer": row.json_pointer,
        "snippet_hash": row.snippet_hash,
        "collected_at": _iso(row.collected_at),
        "confidence": float(row.confidence),
        "redaction": row.redaction,
        "raw_ref": row.raw_ref,
    }


def _fallback_refs(value: str | None) -> list[dict[str, Any]]:
    loaded = _json_load(value, [])
    if not isinstance(loaded, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "source": str(item.get("source") or "unknown"),
                "source_commit": item.get("source_commit"),
                "tool_version": item.get("tool_version"),
                "path": item.get("path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "json_pointer": item.get("json_pointer"),
                "snippet_hash": item.get("snippet_hash"),
                "collected_at": _iso(item.get("collected_at")),
                "confidence": float(item.get("confidence", 1.0)),
                "redaction": str(item.get("redaction") or "partial"),
                "raw_ref": item.get("raw_ref"),
            }
        )
    return refs


def _evidence_projection(
    rows: list[Any], fallback_json: str | None, include_evidence: bool
) -> dict[str, Any]:
    refs = [_evidence_ref(row) for row in rows] or _fallback_refs(fallback_json)
    locations: list[dict[str, Any]] = []
    raw_refs: list[str] = []
    seen_locations: set[tuple[Any, ...]] = set()
    for ref in refs:
        location = {
            "path": ref.get("path"),
            "line_start": ref.get("line_start"),
            "line_end": ref.get("line_end"),
            "json_pointer": ref.get("json_pointer"),
        }
        location_key = tuple(location.values())
        if (
            any(value is not None for value in location.values())
            and location_key not in seen_locations
        ):
            seen_locations.add(location_key)
            locations.append(location)
        raw_ref = ref.get("raw_ref")
        if raw_ref and raw_ref not in raw_refs:
            raw_refs.append(raw_ref)
    result: dict[str, Any] = {
        "count": len(refs),
        "locations": locations,
        "raw_refs": raw_refs,
    }
    if include_evidence:
        result["refs"] = refs
    return result


def _snapshot_payload(snapshot: RepositoryHealthSnapshot) -> dict[str, Any]:
    now = datetime.now(UTC)
    is_stale = snapshot.stale_after_ts is not None and now > snapshot.stale_after_ts
    return {
        "id": snapshot.id,
        "repository_id": snapshot.repository_id,
        "head_sha": snapshot.head_sha,
        "analyzed_at": _iso(snapshot.analyzed_at),
        "as_of_ts": _iso(snapshot.as_of_ts),
        "config_digest": snapshot.config_digest,
        "analyzer_versions_digest": snapshot.analyzer_versions_digest,
        "score_config_digest": snapshot.score_config_digest,
        "scope": snapshot.scope,
        "mode": snapshot.mode,
        "status": snapshot.status,
        "score": float(snapshot.score) if snapshot.score is not None else None,
        "confidence": float(snapshot.confidence),
        "unknown_count": snapshot.unknown_count,
        "error_count": snapshot.error_count,
        "skipped_weight": float(snapshot.skipped_weight),
        "evidence_coverage": float(snapshot.evidence_coverage),
        "criticality": float(snapshot.criticality),
        "stale_after_ts": _iso(snapshot.stale_after_ts),
        "is_stale": is_stale,
        "diagnostics": _json_load(snapshot.diagnostics_json, {}),
    }


async def _get_snapshot(
    session: AsyncSession,
    repository_id: str,
    snapshot_id: str | None,
    scope: str | None,
) -> RepositoryHealthSnapshot | None:
    predicates = [RepositoryHealthSnapshot.repository_id == repository_id]
    if snapshot_id:
        predicates.append(RepositoryHealthSnapshot.id == snapshot_id)
    if scope:
        predicates.append(RepositoryHealthSnapshot.scope == scope)
    result = await session.execute(
        select(RepositoryHealthSnapshot)
        .where(*predicates)
        .order_by(RepositoryHealthSnapshot.as_of_ts.desc(), RepositoryHealthSnapshot.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def build_canonical_health_report(
    session: AsyncSession,
    repository_id: str,
    *,
    snapshot_id: str | None = None,
    scope: str | None = None,
    dimension: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    subject: str | None = None,
    window: str | None = None,
    include_evidence: bool = False,
) -> dict[str, Any] | None:
    """Build the persisted canonical projection without score recomputation."""
    started = perf_counter()
    snapshot = await _get_snapshot(session, repository_id, snapshot_id, scope)
    if snapshot is None:
        log.error(
            "canonical_snapshot_missing repository_id=%s snapshot_id=%s scope=%s",
            repository_id,
            snapshot_id,
            scope,
        )
        return None

    window_start = _parse_window(window)
    snapshot_id_value = snapshot.id
    projection_result = await session.execute(
        select(HealthScoreProjection)
        .where(
            HealthScoreProjection.snapshot_id == snapshot_id_value,
            HealthScoreProjection.score_config_digest == snapshot.score_config_digest,
        )
        .order_by(HealthScoreProjection.created_at.desc(), HealthScoreProjection.id.desc())
        .limit(1)
    )
    score_projection = projection_result.scalar_one_or_none()
    if score_projection is None:
        # Existing 0064 databases may not have a projection for old snapshots.
        legacy_projection_result = await session.execute(
            select(HealthScoreProjection)
            .where(HealthScoreProjection.snapshot_id == snapshot_id_value)
            .order_by(HealthScoreProjection.created_at.desc(), HealthScoreProjection.id.desc())
            .limit(1)
        )
        score_projection = legacy_projection_result.scalar_one_or_none()

    metric_predicates = [HealthMetricValue.snapshot_id == snapshot_id_value]
    if dimension:
        metric_predicates.append(
            or_(
                HealthMetricValue.name == dimension,
                HealthMetricValue.name.startswith(f"{dimension}:"),
                HealthMetricValue.analyzer_id == dimension,
                HealthMetricValue.analyzer_id.startswith(f"{dimension}."),
            )
        )
    if window_start:
        metric_predicates.append(
            or_(
                HealthMetricValue.window_end.is_(None),
                HealthMetricValue.window_end >= window_start,
            )
        )
    metric_rows = list(
        (
            await session.execute(
                select(HealthMetricValue)
                .where(and_(*metric_predicates))
                .order_by(HealthMetricValue.analyzer_id, HealthMetricValue.name)
            )
        )
        .scalars()
        .all()
    )

    aggregate_predicates = [HealthAggregate.snapshot_id == snapshot_id_value]
    if dimension:
        aggregate_predicates.append(HealthAggregate.dimension == dimension)
    aggregate_rows = list(
        (
            await session.execute(
                select(HealthAggregate)
                .where(and_(*aggregate_predicates))
                .order_by(HealthAggregate.dimension, HealthAggregate.name)
            )
        )
        .scalars()
        .all()
    )

    recommendation_predicates = [HealthRecommendation.snapshot_id == snapshot_id_value]
    if dimension:
        recommendation_predicates.append(HealthRecommendation.dimension == dimension)
    if status:
        recommendation_predicates.append(HealthRecommendation.finding_status == status)
    if severity:
        recommendation_predicates.append(HealthRecommendation.severity == severity)
    if subject:
        recommendation_predicates.append(HealthRecommendation.subject.ilike(f"%{subject}%"))
    if window_start:
        recommendation_predicates.append(
            or_(
                HealthRecommendation.last_seen_at.is_(None),
                HealthRecommendation.last_seen_at >= window_start,
            )
        )
    recommendation_rows = list(
        (
            await session.execute(
                select(HealthRecommendation)
                .where(and_(*recommendation_predicates))
                .order_by(
                    HealthRecommendation.priority.desc(), HealthRecommendation.recommendation_id
                )
            )
        )
        .scalars()
        .all()
    )

    evidence_rows = list(
        (
            await session.execute(
                select(HealthFindingEvidence)
                .where(HealthFindingEvidence.snapshot_id == snapshot_id_value)
                .order_by(HealthFindingEvidence.finding_id, HealthFindingEvidence.id)
            )
        )
        .scalars()
        .all()
    )
    evidence_by_finding: dict[str, list[Any]] = {}
    for row in evidence_rows:
        evidence_by_finding.setdefault(row.finding_id, []).append(row)

    source_rows = list(
        (
            await session.execute(
                select(HealthSourceRun)
                .where(HealthSourceRun.snapshot_id == snapshot_id_value)
                .order_by(HealthSourceRun.analyzer_id, HealthSourceRun.source)
            )
        )
        .scalars()
        .all()
    )

    def metric_payload(row: HealthMetricValue) -> dict[str, Any]:
        provenance = _json_load(row.provenance_json, [])
        if not isinstance(provenance, list):
            provenance = []
        payload = {
            "id": row.id,
            "analyzer_id": row.analyzer_id,
            "name": row.name,
            "dimension": row.dimension,
            "value": _json_load(row.value_json, None),
            "numeric_value": row.numeric_value,
            "unit": row.unit,
            "score": row.score,
            "population": row.population,
            "denominator": row.denominator,
            "weight": row.weight,
            "available_weight": row.available_weight,
            "window_start": _iso(row.window_start),
            "window_end": _iso(row.window_end),
            "evidence_summary": {
                "count": len(provenance),
                "sources": sorted(
                    {
                        str(item.get("source"))
                        for item in provenance
                        if isinstance(item, dict) and item.get("source")
                    }
                ),
            },
        }
        if include_evidence:
            payload["provenance"] = provenance
        return payload

    finding_payload: list[dict[str, Any]] = []
    for row in recommendation_rows:
        refs = evidence_by_finding.get(row.finding_id or "", [])
        evidence = _evidence_projection(refs, row.evidence_json, include_evidence)
        finding_payload.append(
            {
                "id": row.finding_id or row.recommendation_id,
                "recommendation_id": row.recommendation_id,
                "finding_id": row.finding_id,
                "subject": row.subject,
                "dimension": row.dimension,
                "status": row.finding_status,
                "severity": row.severity,
                "reason": row.reason,
                "remediation": row.remediation,
                "location": _json_load(row.location_json, {}),
                "priority": row.priority,
                "lifecycle": row.lifecycle,
                "benefit": row.benefit,
                "confidence": row.confidence,
                "criticality": row.criticality,
                "effort": row.effort,
                "risk": row.risk,
                "blast_radius": row.blast_radius,
                "raw_impact": row.raw_impact,
                "applied_impact": row.applied_impact,
                "first_seen_at": _iso(row.first_seen_at),
                "last_seen_at": _iso(row.last_seen_at),
                "evidence": evidence,
            }
        )

    legacy_dimensions = [
        {
            "dimension": row.dimension,
            "name": row.name,
            "scope": row.scope,
            "value": row.value,
            "score": row.score,
            "unknown_count": row.unknown_count,
            "error_count": row.error_count,
            "skipped_weight": row.skipped_weight,
            "evidence_coverage": row.evidence_coverage,
            "criticality": row.criticality,
            "provenance": _json_load(row.provenance_json, [])
            if include_evidence
            else {"count": len(_json_load(row.provenance_json, []))},
        }
        for row in aggregate_rows
    ]
    projection_dimensions = _json_load(score_projection.dimensions_json, {}) if score_projection else {}
    if not isinstance(projection_dimensions, dict):
        projection_dimensions = {}
    dimensions = (
        [
            {
                "dimension": dimension_name,
                "name": "composite",
                "scope": "repository",
                "value": score,
                "score": score,
                "unknown_count": 0,
                "error_count": 0,
                "skipped_weight": 0.0,
                "evidence_coverage": score_projection.evidence_coverage if score_projection else 0.0,
                "criticality": 0.0,
                "provenance": {"count": 0},
            }
            for dimension_name, score in sorted(projection_dimensions.items())
        ]
        if score_projection is not None
        else legacy_dimensions
    )

    metric_evidence_count = 0
    metric_sources: dict[str, int] = {}
    for row in metric_rows:
        provenance = _json_load(row.provenance_json, [])
        if isinstance(provenance, list):
            metric_evidence_count += len(provenance)
            for item in provenance:
                if isinstance(item, dict) and item.get("source"):
                    source_name = str(item["source"])
                    metric_sources[source_name] = metric_sources.get(source_name, 0) + 1
    finding_evidence_count = sum(
        len(evidence_by_finding.get(row.finding_id or "", []))
        or len(_fallback_refs(row.evidence_json))
        for row in recommendation_rows
    )
    by_source = dict(metric_sources)
    for row in evidence_rows:
        by_source[row.source] = by_source.get(row.source, 0) + 1
    covered_metrics = sum(bool(_json_load(row.provenance_json, [])) for row in metric_rows)
    total_evidence_count = metric_evidence_count + finding_evidence_count
    coverage = {
        "metric_count": len(metric_rows),
        "metric_evidence_count": metric_evidence_count,
        "finding_count": len(finding_payload),
        "finding_evidence_count": finding_evidence_count,
        "total_evidence_count": total_evidence_count,
        "covered_metrics": covered_metrics,
        "evidence_coverage": float(snapshot.evidence_coverage),
        "by_source": by_source,
    }

    limitations: list[dict[str, Any]] = []
    if snapshot.unknown_count:
        limitations.append(
            {
                "code": "unknown_analyzers",
                "message": "Some analyzers returned inconclusive data.",
                "affected": snapshot.unknown_count,
            }
        )
    if snapshot.error_count:
        limitations.append(
            {
                "code": "analyzer_errors",
                "message": "Some analyzers failed; their dimensions are not complete.",
                "affected": snapshot.error_count,
            }
        )
    if snapshot.skipped_weight:
        limitations.append(
            {
                "code": "skipped_weight",
                "message": "Part of the configured analyzer weight was skipped.",
                "affected": snapshot.skipped_weight,
            }
        )
    if snapshot.evidence_coverage < 1.0:
        limitations.append(
            {
                "code": "partial_evidence",
                "message": "Not every stored metric has traceable evidence.",
                "affected": snapshot.evidence_coverage,
            }
        )
    if score_projection is not None:
        projection_limitations = _json_load(score_projection.limitations_json, [])
        if isinstance(projection_limitations, list):
            for item in projection_limitations:
                if not isinstance(item, dict):
                    continue
                limitations.append(
                    {
                        "code": str(item.get("kind") or "score_quality"),
                        "message": str(item.get("reason") or "Score quality limitation."),
                        "affected": item.get("affected_scope"),
                    }
                )
    if snapshot.stale_after_ts is not None and datetime.now(UTC) > snapshot.stale_after_ts:
        limitations.append(
            {
                "code": "stale_snapshot",
                "message": "The persisted snapshot is past its freshness deadline.",
                "affected": _iso(snapshot.stale_after_ts),
            }
        )

    analyzers = [
        {
            "analyzer_id": row.analyzer_id,
            "source": row.source,
            "source_commit": row.source_commit,
            "tool_version": row.tool_version,
            "status": row.status,
            "duration_ms": row.duration_ms,
            "raw_fact_count": row.raw_fact_count,
            "diagnostics": _json_load(row.diagnostic_json, {}),
        }
        for row in source_rows
    ]
    payload = {
        "schema_version": 1,
        "repository_id": repository_id,
        "snapshot": _snapshot_payload(snapshot),
        "dimensions": dimensions,
        "score_projection": (
            {
                "id": score_projection.id,
                "score_config_digest": score_projection.score_config_digest,
                "overall_score": score_projection.overall_score,
                "dimensions": projection_dimensions,
                "breakdown": _json_load(score_projection.breakdown_json, []),
                "configured_weight": score_projection.configured_weight,
                "available_weight": score_projection.available_weight,
                "confidence": score_projection.confidence,
                "coverage": score_projection.coverage,
                "evidence_coverage": score_projection.evidence_coverage,
                "status": score_projection.status,
                "limitations": _json_load(score_projection.limitations_json, []),
                "score_recomputed": score_projection.score_recomputed,
            }
            if score_projection is not None
            else None
        ),
        "metrics": [metric_payload(row) for row in metric_rows],
        "findings": finding_payload,
        "recommendations": finding_payload,
        "analyzers": analyzers,
        "coverage": coverage,
        "limitations": limitations,
        "criticality": {
            "score": float(snapshot.criticality),
            "applied_to_score": False,
            "used_for_recommendation_priority": True,
        },
        "meta": {
            "read_model": "repository_health_envelope",
            "score_recomputed": bool(score_projection.score_recomputed) if score_projection else False,
            "include_evidence": include_evidence,
            "filters": {
                "snapshot": snapshot_id,
                "scope": scope,
                "dimension": dimension,
                "status": status,
                "severity": severity,
                "subject": subject,
                "window": window,
            },
            "evidence_detail": "included" if include_evidence else "summary_only",
        },
    }
    report = CanonicalHealthReport.model_validate(payload).model_dump(mode="json")
    log.info(
        "canonical_projection repository_id=%s snapshot_id=%s metrics=%d findings=%d evidence=%s duration_ms=%.2f",
        repository_id,
        snapshot.id,
        len(metric_rows),
        len(finding_payload),
        include_evidence,
        (perf_counter() - started) * 1000,
    )
    return report
