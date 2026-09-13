"""Atomic persistence and replay helpers for the canonical health envelope."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....analysis.health.composite import (
    CompositeHealthScore,
    CompositeScoreConfig,
    compose_health_score,
)
from ....analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    MetricValue,
)
from ....analysis.health.integrations.finding_merge import deduplicate_findings
from ....analysis.health.integrations.forge_adapter import RawFact
from ....analysis.health.integrations.identity_adapter import IdentityResolver
from ....analysis.health.integrations.temporal_adapter import (
    EventNormalizer,
    raw_facts_from_context,
)
from ...models import (
    HealthAggregate,
    HealthFindingEvidence,
    HealthMetricValue,
    HealthNormalizedFact,
    HealthRawFact,
    HealthRecommendation,
    HealthScoreProjection,
    HealthSourceRun,
    RepositoryHealthSnapshot,
    _new_uuid,
    _now_utc,
)
from .health_ranking import publish_health_ranking

log = structlog.get_logger("health.persistence")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _utc(value: object, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
        except ValueError:
            pass
    return fallback.astimezone(UTC)


def _ref_dump(ref: Any) -> dict[str, Any]:
    if hasattr(ref, "model_dump"):
        return ref.model_dump(mode="json")
    return dict(ref) if isinstance(ref, Mapping) else {}


def _result_score(
    results: Iterable[AnalyzerResult],
    config: CompositeScoreConfig | Mapping[str, Any] | None = None,
    *,
    repository_id: str | None = None,
) -> float | None:
    """Return the canonical composite score, never first-result score."""
    composed = compose_health_score(results, config, repository_id=repository_id)
    return composed.overall


def _composite_score(
    results: Iterable[AnalyzerResult],
    config: CompositeScoreConfig | Mapping[str, Any] | None = None,
    *,
    repository_id: str | None = None,
) -> CompositeHealthScore:
    return compose_health_score(results, config, repository_id=repository_id)


def _result_status(results: Iterable[AnalyzerResult]) -> str:
    statuses = {result.status.value for result in results}
    if "error" in statuses:
        return "error"
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if statuses == {"pass"}:
        return "pass"
    return "inconclusive"


def _stale_after(context: AnalyzerContext, as_of: datetime) -> datetime | None:
    """Resolve an optional freshness deadline without making it a score input."""
    value = context.inventory.get("stale_after")
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return as_of + timedelta(seconds=max(0.0, float(value)))
    return None


def _raw_records(context: AnalyzerContext) -> tuple[RawFact, ...]:
    """Deduplicate raw source events without changing their payloads."""
    facts = raw_facts_from_context(context)
    unique: dict[tuple[str, str, str | None], RawFact] = {}
    for fact in facts:
        key = (fact.source, fact.stable_event_id, fact.source_version)
        unique.setdefault(key, fact)
    return tuple(unique.values())


def _finding_factors(
    context: AnalyzerContext, finding: Any
) -> tuple[float, float, float, float, float, float, float]:
    configured = context.inventory.get("recommendation_factors")
    row = configured.get(finding.id) if isinstance(configured, Mapping) else None
    row = row if isinstance(row, Mapping) else {}
    benefit = float(row.get("benefit") or finding.raw_impact or finding.applied_impact or 1.0)
    confidence = max(0.0, min(1.0, float(row.get("confidence") or finding.confidence)))
    criticality = max(0.0, min(1.0, float(row.get("criticality") if row.get("criticality") is not None else 1.0)))
    effort = max(0.01, float(row.get("effort") or 1.0))
    risk = max(0.01, float(row.get("risk") or 1.0))
    blast = max(0.01, float(row.get("blast_radius") or 1.0))
    priority = benefit * confidence * criticality / (effort * risk * blast)
    return priority, benefit, confidence, criticality, effort, risk, blast


async def save_health_envelope(
    session: AsyncSession,
    repository_id: str,
    context: AnalyzerContext,
    results: Iterable[AnalyzerResult],
    *,
    config_digest: str | None = None,
    score_config_digest: str | None = None,
) -> RepositoryHealthSnapshot:
    """Write one snapshot in raw → normalized → derived order.

    The caller owns the transaction.  A repeated replay key returns the
    existing snapshot without touching immutable source rows.
    """
    materialized_results = deduplicate_findings(tuple(results))
    analyzer_digest = _hash(sorted(f"{result.analyzer_id}:{result.analyzer_version}" for result in materialized_results))
    effective_config = str(config_digest or context.config_digest or "")
    composite = _composite_score(materialized_results, repository_id=repository_id)
    effective_score_config = str(score_config_digest or composite.score_config_digest)
    as_of = context.as_of_ts.astimezone(UTC)
    existing_query = await session.execute(
        select(RepositoryHealthSnapshot).where(
            RepositoryHealthSnapshot.repository_id == repository_id,
            RepositoryHealthSnapshot.head_sha == context.head_sha,
            RepositoryHealthSnapshot.as_of_ts == as_of,
            RepositoryHealthSnapshot.config_digest == effective_config,
            RepositoryHealthSnapshot.analyzer_versions_digest == analyzer_digest,
            RepositoryHealthSnapshot.scope == context.scope,
        )
    )
    existing = existing_query.scalar_one_or_none()
    if existing is not None:
        log.warning("duplicate_snapshot_replay repository_id=%s snapshot_id=%s", repository_id, existing.id)
        return existing

    snapshot = RepositoryHealthSnapshot(
        id=_new_uuid(),
        repository_id=repository_id,
        head_sha=context.head_sha,
        analyzed_at=as_of,
        as_of_ts=as_of,
        config_digest=effective_config,
        analyzer_versions_digest=analyzer_digest,
        score_config_digest=effective_score_config,
        scope=context.scope,
        mode=context.mode,
        status=_result_status(materialized_results),
        score=composite.overall,
        confidence=composite.confidence,
        unknown_count=sum(result.status.value == "inconclusive" for result in materialized_results),
        error_count=sum(result.status.value == "error" for result in materialized_results),
        skipped_weight=max(0.0, composite.configured_weight - composite.available_weight),
        evidence_coverage=composite.evidence_coverage,
        criticality=max(0.0, min(1.0, float(context.inventory.get("criticality") or 0.0))),
        stale_after_ts=_stale_after(context, as_of),
        diagnostics_json=_json({
            "analyzer_ids": [result.analyzer_id for result in materialized_results],
            "source_order": "raw-normalized-derived",
            "composite": composite.model_dump(mode="json"),
        }),
        created_at=_now_utc(),
    )
    session.add(snapshot)
    await session.flush()
    log.debug("snapshot_created repository_id=%s snapshot_id=%s", repository_id, snapshot.id)

    source_runs: dict[tuple[str, str], HealthSourceRun] = {}
    for result in materialized_results:
        versions = result.source_versions or {result.analyzer_id: result.analyzer_version}
        for source, version in sorted(versions.items()):
            source_run = HealthSourceRun(
                id=_new_uuid(),
                snapshot_id=snapshot.id,
                analyzer_id=result.analyzer_id,
                source=source,
                source_commit=version,
                tool_version=result.analyzer_version,
                status=result.status.value,
                duration_ms=result.duration_ms,
                raw_fact_count=int(result.diagnostics.get("raw_fact_count") or 0),
                diagnostic_json=_json(result.diagnostics),
                started_at=as_of,
                finished_at=as_of,
            )
            session.add(source_run)
            source_runs[(result.analyzer_id, source)] = source_run
    await session.flush()
    log.debug("source_runs_written snapshot_id=%s count=%d", snapshot.id, len(source_runs))

    raw_rows: dict[tuple[str, str, str | None], HealthRawFact] = {}
    for fact in _raw_records(context):
        source_run = next((row for (analyzer, source), row in source_runs.items() if source == fact.source), None)
        payload = dict(fact.payload)
        row = HealthRawFact(
            id=_new_uuid(),
            snapshot_id=snapshot.id,
            source_run_id=source_run.id if source_run else None,
            source=fact.source,
            source_commit=fact.source_version,
            tool_version=source_run.tool_version if source_run else None,
            event_type=fact.event_type,
            stable_event_id=fact.stable_event_id,
            collected_at=fact.updated_at or as_of,
            updated_at=fact.updated_at,
            payload_json=_json(payload),
            payload_ref=f"raw://{fact.source}/{fact.stable_event_id}",
            payload_hash=_hash(payload),
            redaction="partial",
            window_start=fact.window_start,
            window_end=fact.window_end,
        )
        session.add(row)
        raw_rows[(fact.source, fact.stable_event_id, fact.source_version)] = row
    await session.flush()
    log.info("raw_facts_written snapshot_id=%s count=%d", snapshot.id, len(raw_rows))

    resolver = IdentityResolver(context)
    normalizer = EventNormalizer(context)
    normalized_rows = []
    for fact in _raw_records(context):
        normalized = normalizer.normalize(fact)
        author = normalized.payload.get("author") or normalized.payload.get("user") or normalized.payload.get("contributor")
        match = resolver.resolve(author) if isinstance(author, Mapping) else None
        raw_row = raw_rows[(fact.source, fact.stable_event_id, fact.source_version)]
        normalized_rows.append(
            HealthNormalizedFact(
                id=_new_uuid(),
                snapshot_id=snapshot.id,
                raw_fact_id=raw_row.id,
                fact_type=normalized.event_type,
                stable_event_id=normalized.stable_event_id,
                canonical_contributor_id=match.canonical_contributor_id if match else None,
                normalized_ts=normalized.normalized_ts,
                original_offset_minutes=normalized.original_offset_minutes,
                timestamp_corrected=normalized.timestamp_corrected,
                identity_confidence=match.confidence if match else None,
                normalization_policy=normalized.normalization_policy,
                payload_json=_json(dict(normalized.payload)),
                source_event_ref=f"{normalized.source}:{normalized.stable_event_id}",
                created_at=_now_utc(),
            )
        )
    session.add_all(normalized_rows)
    await session.flush()
    log.info("normalized_facts_written snapshot_id=%s count=%d", snapshot.id, len(normalized_rows))

    metric_rows = []
    for result in materialized_results:
        for metric in result.metrics:
            numeric = None
            if isinstance(metric.value, (int, float)) and not isinstance(metric.value, bool):
                numeric = float(metric.value)
            diagnostics = result.diagnostics
            metric_rows.append(
                HealthMetricValue(
                    id=_new_uuid(),
                    snapshot_id=snapshot.id,
                    analyzer_id=result.analyzer_id,
                    name=metric.name,
                    dimension=metric.dimension,
                    value_json=_json(metric.value),
                    numeric_value=numeric,
                    unit=metric.unit,
                    score=metric.score,
                    population=metric.population,
                    denominator=metric.denominator,
                    weight=result.total_weight / len(result.metrics) if result.metrics else 0.0,
                    available_weight=result.available_weight / len(result.metrics) if result.metrics else 0.0,
                    window_start=_utc(diagnostics.get("start_ts"), as_of) if diagnostics.get("start_ts") else None,
                    window_end=_utc(diagnostics.get("end_ts"), as_of) if diagnostics.get("end_ts") else None,
                    provenance_json=_json([_ref_dump(ref) for ref in metric.evidence_refs]),
                )
            )
    session.add_all(metric_rows)
    await session.flush()

    evidence_rows = []
    recommendations = []
    for result in materialized_results:
        for finding in result.findings:
            for ref in finding.evidence_refs:
                evidence_rows.append(
                    HealthFindingEvidence(
                        id=_new_uuid(),
                        snapshot_id=snapshot.id,
                        finding_id=finding.id,
                        analyzer_id=finding.analyzer_id,
                        source=ref.source,
                        source_commit=ref.source_commit,
                        tool_version=ref.tool_version,
                        path=ref.path,
                        line_start=ref.line_start,
                        line_end=ref.line_end,
                        json_pointer=ref.json_pointer,
                        snippet_hash=ref.snippet_hash,
                        collected_at=ref.collected_at,
                        confidence=ref.confidence,
                        redaction=ref.redaction,
                        raw_ref=result.raw_payload_ref,
                    )
                )
            priority, benefit, confidence, criticality, effort, risk, blast = _finding_factors(
                context, finding
            )
            recommendation_id = "rec:" + hashlib.sha256(f"{finding.analyzer_id}:{finding.id}:{finding.subject}".encode()).hexdigest()[:32]
            first_seen = _utc(getattr(finding, "first_seen_at", None), as_of) if getattr(finding, "first_seen_at", None) else as_of
            last_seen = _utc(getattr(finding, "last_seen_at", None), as_of) if getattr(finding, "last_seen_at", None) else as_of
            recommendations.append(
                HealthRecommendation(
                    id=_new_uuid(),
                    snapshot_id=snapshot.id,
                    recommendation_id=recommendation_id,
                    finding_id=finding.id,
                    subject=finding.subject,
                    dimension=finding.dimension,
                    finding_status=str(getattr(finding, "status", "open") or "open"),
                    severity=str(finding.severity),
                    reason=finding.reason,
                    remediation=finding.remediation,
                    location_json=_json(finding.location.model_dump(mode="json") if finding.location else {}),
                    priority=priority,
                    lifecycle="new",
                    benefit=benefit,
                    confidence=confidence,
                    criticality=criticality,
                    effort=effort,
                    risk=risk,
                    blast_radius=blast,
                    raw_impact=finding.raw_impact,
                    applied_impact=finding.applied_impact,
                    evidence_json=_json([_ref_dump(ref) for ref in finding.evidence_refs]),
                    first_seen_at=first_seen,
                    last_seen_at=last_seen,
                    created_at=_now_utc(),
                    updated_at=_now_utc(),
                )
            )
    session.add_all(evidence_rows)
    await session.flush()
    log.debug("finding_evidence_written snapshot_id=%s count=%d", snapshot.id, len(evidence_rows))

    aggregates = []
    for result in materialized_results:
        dimension = result.analyzer_id.split(".", 1)[0]
        aggregates.append(
            HealthAggregate(
                id=_new_uuid(),
                snapshot_id=snapshot.id,
                score_config_digest=effective_score_config,
                scope=context.scope,
                dimension=dimension,
                name=result.analyzer_id,
                value=result.score,
                score=result.score,
                unknown_count=int(result.status.value == "inconclusive"),
                error_count=int(result.status.value == "error"),
                skipped_weight=max(0.0, result.total_weight - result.available_weight),
                evidence_coverage=min(1.0, len(result.evidence) / max(1, len(result.metrics))),
                criticality=snapshot.criticality,
                provenance_json=_json([_ref_dump(ref) for ref in result.evidence]),
                created_at=_now_utc(),
            )
        )
    session.add_all(aggregates)
    await session.flush()
    session.add_all(recommendations)
    await session.flush()
    score_projection = HealthScoreProjection(
            id=_new_uuid(),
            snapshot_id=snapshot.id,
            score_config_digest=effective_score_config,
            overall_score=composite.overall,
            dimensions_json=_json(composite.dimensions),
            breakdown_json=_json(list(composite.breakdown)),
            configured_weight=composite.configured_weight,
            available_weight=composite.available_weight,
            confidence=composite.confidence,
            coverage=composite.coverage,
            evidence_coverage=composite.evidence_coverage,
            status=composite.status.value,
            limitations_json=_json([item.model_dump(mode="json") for item in composite.limitations]),
            score_recomputed=False,
            created_at=_now_utc(),
        )
    session.add(score_projection)
    await session.flush()
    await publish_health_ranking(session, repository_id, snapshot, score_projection)
    log.info("snapshot_committed_pending repository_id=%s snapshot_id=%s metrics=%d findings=%d recommendations=%d", repository_id, snapshot.id, len(metric_rows), len(evidence_rows), len(recommendations))
    return snapshot


async def load_health_snapshot_envelope(session: AsyncSession, snapshot_id: str) -> dict[str, Any] | None:
    """Read one canonical projection without recalculating score."""
    snapshot_result = await session.execute(select(RepositoryHealthSnapshot).where(RepositoryHealthSnapshot.id == snapshot_id))
    snapshot = snapshot_result.scalar_one_or_none()
    if snapshot is None:
        return None
    metric_result = await session.execute(select(HealthMetricValue).where(HealthMetricValue.snapshot_id == snapshot_id).order_by(HealthMetricValue.analyzer_id, HealthMetricValue.name))
    finding_result = await session.execute(select(HealthFindingEvidence).where(HealthFindingEvidence.snapshot_id == snapshot_id).order_by(HealthFindingEvidence.finding_id, HealthFindingEvidence.id))
    aggregate_result = await session.execute(select(HealthAggregate).where(HealthAggregate.snapshot_id == snapshot_id).order_by(HealthAggregate.dimension, HealthAggregate.name))
    projection_result = await session.execute(
        select(HealthScoreProjection)
        .where(HealthScoreProjection.snapshot_id == snapshot_id)
        .order_by(HealthScoreProjection.created_at.desc(), HealthScoreProjection.id.desc())
        .limit(1)
    )
    projection = projection_result.scalar_one_or_none()
    recommendation_result = await session.execute(select(HealthRecommendation).where(HealthRecommendation.snapshot_id == snapshot_id).order_by(HealthRecommendation.priority.desc(), HealthRecommendation.recommendation_id))
    return {
        "snapshot": {column.name: getattr(snapshot, column.name) for column in RepositoryHealthSnapshot.__table__.columns},
        "metrics": [{column.name: getattr(row, column.name) for column in HealthMetricValue.__table__.columns} for row in metric_result.scalars().all()],
        "evidence": [{column.name: getattr(row, column.name) for column in HealthFindingEvidence.__table__.columns} for row in finding_result.scalars().all()],
        "aggregates": [{column.name: getattr(row, column.name) for column in HealthAggregate.__table__.columns} for row in aggregate_result.scalars().all()],
        "score_projection": ({column.name: getattr(projection, column.name) for column in HealthScoreProjection.__table__.columns} if projection else None),
        "recommendations": [{column.name: getattr(row, column.name) for column in HealthRecommendation.__table__.columns} for row in recommendation_result.scalars().all()],
    }


async def compare_health_snapshots(
    session: AsyncSession,
    current_snapshot_id: str,
    previous_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Compare persisted snapshots without recalculating any analyzer score."""
    current_result = await session.execute(
        select(RepositoryHealthSnapshot).where(RepositoryHealthSnapshot.id == current_snapshot_id)
    )
    current = current_result.scalar_one_or_none()
    if current is None:
        raise ValueError(f"unknown health snapshot: {current_snapshot_id}")
    if previous_snapshot_id:
        previous_result = await session.execute(
            select(RepositoryHealthSnapshot).where(RepositoryHealthSnapshot.id == previous_snapshot_id)
        )
    else:
        previous_result = await session.execute(
            select(RepositoryHealthSnapshot)
            .where(
                RepositoryHealthSnapshot.repository_id == current.repository_id,
                RepositoryHealthSnapshot.as_of_ts < current.as_of_ts,
            )
            .order_by(RepositoryHealthSnapshot.as_of_ts.desc())
            .limit(1)
        )
    previous = previous_result.scalar_one_or_none()

    async def _aggregates(snapshot_id: str) -> dict[str, float | None]:
        result = await session.execute(
            select(HealthAggregate.dimension, HealthAggregate.score)
            .where(
                HealthAggregate.snapshot_id == snapshot_id,
                HealthAggregate.score_config_digest == current.score_config_digest,
            )
        )
        return {dimension: score for dimension, score in result.all()}

    current_dimensions = await _aggregates(current.id)
    previous_dimensions = await _aggregates(previous.id) if previous else {}
    dimensions = {}
    for dimension in sorted(set(current_dimensions) | set(previous_dimensions)):
        before = previous_dimensions.get(dimension)
        after = current_dimensions.get(dimension)
        dimensions[dimension] = {
            "before": before,
            "after": after,
            "delta": after - before if after is not None and before is not None else None,
        }
    now = _now_utc()
    is_stale = current.stale_after_ts is not None and now > current.stale_after_ts
    score_delta = current.score - previous.score if previous and current.score is not None and previous.score is not None else None
    attribution = "history_or_external" if score_delta is not None and score_delta < 0 else "none"
    return {
        "current_snapshot_id": current.id,
        "previous_snapshot_id": previous.id if previous else None,
        "score": current.score,
        "score_delta": score_delta,
        "status": current.status,
        "is_stale": is_stale,
        "stale_after_ts": current.stale_after_ts,
        "decline_attribution": attribution,
        "dimensions": dimensions,
    }


async def rescore_health_snapshot(
    session: AsyncSession,
    snapshot_id: str,
    score_config: Mapping[str, Any],
    *,
    score_config_digest: str | None = None,
) -> list[HealthAggregate]:
    """Recompute aggregates from stored metric rows only."""
    snapshot_result = await session.execute(select(RepositoryHealthSnapshot).where(RepositoryHealthSnapshot.id == snapshot_id))
    snapshot = snapshot_result.scalar_one_or_none()
    if snapshot is None:
        raise ValueError(f"unknown health snapshot: {snapshot_id}")
    digest = str(score_config_digest or _hash(score_config))
    existing_result = await session.execute(select(HealthAggregate).where(HealthAggregate.snapshot_id == snapshot_id, HealthAggregate.score_config_digest == digest))
    existing = list(existing_result.scalars().all())
    if existing:
        return existing
    metrics_result = await session.execute(select(HealthMetricValue).where(HealthMetricValue.snapshot_id == snapshot_id))
    metrics = list(metrics_result.scalars().all())
    weights = score_config.get("weights") if isinstance(score_config.get("weights"), Mapping) else {}
    canonical_names = {"code", "history", "tests", "dependencies", "security", "delivery", "community", "docs"}
    canonical_mode = not weights or any(str(key).strip().lower() in canonical_names for key in weights)
    grouped: dict[str, list[tuple[HealthMetricValue, float]]] = {}
    for metric in metrics:
        dimension = metric.dimension or metric.name.split(":", 1)[0]
        configured_weight = weights.get(metric.name, weights.get(dimension, 1.0)) if isinstance(weights, Mapping) else 1.0
        try:
            weight = max(0.0, float(configured_weight))
        except (TypeError, ValueError):
            weight = 1.0
        if metric.score is not None and weight:
            grouped.setdefault(dimension, []).append((metric, weight))
    aggregates: list[HealthAggregate] = []
    for dimension, rows in sorted(grouped.items()):
        total = sum(weight for _metric, weight in rows)
        score = sum(float(metric.score or 0.0) * weight for metric, weight in rows) / total if total else None
        aggregates.append(
            HealthAggregate(
                id=_new_uuid(),
                snapshot_id=snapshot_id,
                score_config_digest=digest,
                scope=snapshot.scope,
                dimension=dimension,
                name=f"rescore:{dimension}",
                value=score,
                score=score,
                unknown_count=0,
                error_count=0,
                skipped_weight=0.0,
                evidence_coverage=sum(bool(metric.provenance_json and metric.provenance_json != "[]") for metric, _weight in rows) / len(rows),
                criticality=snapshot.criticality,
                provenance_json=_json({"source_snapshot_id": snapshot_id, "metric_names": [metric.name for metric, _weight in rows], "score_config_digest": digest}),
                created_at=_now_utc(),
            )
        )
    session.add_all(aggregates)
    await session.flush()

    if canonical_mode:
        persisted_results: list[AnalyzerResult] = []
        for metric in metrics:
            if metric.score is None or metric.denominator is None or metric.denominator <= 0:
                continue
            refs: list[EvidenceRef] = []
            try:
                raw_refs = json.loads(metric.provenance_json or "[]")
            except (TypeError, ValueError):
                raw_refs = []
            for raw_ref in raw_refs if isinstance(raw_refs, list) else []:
                try:
                    refs.append(EvidenceRef.model_validate(raw_ref))
                except (TypeError, ValueError):
                    continue
            if not refs:
                refs.append(EvidenceRef(source=metric.analyzer_id, collected_at=snapshot.as_of_ts))
            try:
                value = json.loads(metric.value_json or "null")
            except (TypeError, ValueError):
                value = None
            persisted_results.append(
                AnalyzerResult(
                    analyzer_id=metric.analyzer_id,
                    analyzer_version="persisted",
                    status=AnalyzerStatus.PASS,
                    metrics=(
                        MetricValue(
                            name=metric.name,
                            dimension=metric.dimension,
                            value=value,
                            unit=metric.unit,
                            score=metric.score,
                            population=metric.population,
                            denominator=metric.denominator,
                            evidence_refs=tuple(refs),
                        ),
                    ),
                    evidence=tuple(refs),
                    available_weight=1,
                    total_weight=1,
                )
            )
        composed = compose_health_score(persisted_results, score_config, repository_id=snapshot.repository_id)
        projection_overall = composed.overall
        projection_dimensions = composed.dimensions
        projection_configured = composed.configured_weight
        projection_available = composed.available_weight
        projection_confidence = composed.confidence
        projection_coverage = composed.coverage
        projection_evidence = composed.evidence_coverage
        projection_status = composed.status.value
        projection_limitations = [item.model_dump(mode="json") for item in composed.limitations]
        breakdown = list(composed.breakdown)
    else:
        legacy_rows = [
            (metric, max(0.0, float(weights.get(metric.name, 1.0))))
            for metric in metrics
            if metric.score is not None and max(0.0, float(weights.get(metric.name, 1.0))) > 0
        ]
        legacy_total = sum(weight for _metric, weight in legacy_rows)
        projection_overall = (
            sum(float(metric.score or 0.0) * weight for metric, weight in legacy_rows) / legacy_total
            if legacy_total
            else None
        )
        projection_dimensions = {
            dimension: (
                sum(float(metric.score or 0.0) * weight for metric, weight in rows) / sum(weight for _metric, weight in rows)
                if rows
                else None
            )
            for dimension, rows in sorted(grouped.items())
        }
        projection_configured = legacy_total
        projection_available = legacy_total
        projection_confidence = 1.0 if legacy_rows else 0.0
        projection_coverage = 1.0 if legacy_rows else 0.0
        projection_evidence = projection_coverage
        projection_status = snapshot.status
        projection_limitations = [] if legacy_rows else [{"reason": "No stored scored metrics", "kind": "insufficient_denominator"}]
        breakdown = [
            {
                "analyzer_id": metric.analyzer_id,
                "source": metric.analyzer_id,
                "dimension": metric.dimension or metric.name.split(":", 1)[0],
                "metric_name": metric.name,
                "score": metric.score,
                "weight": weight,
            }
            for metric, weight in legacy_rows
        ]
    score_projection = HealthScoreProjection(
            id=_new_uuid(),
            snapshot_id=snapshot_id,
            score_config_digest=digest,
            overall_score=projection_overall,
            dimensions_json=_json(projection_dimensions),
            breakdown_json=_json(breakdown),
            configured_weight=projection_configured,
            available_weight=projection_available,
            confidence=projection_confidence,
            coverage=projection_coverage,
            evidence_coverage=projection_evidence,
            status=projection_status,
            limitations_json=_json(projection_limitations),
            score_recomputed=True,
            created_at=_now_utc(),
        )
    session.add(score_projection)
    snapshot.score = projection_overall
    snapshot.score_config_digest = digest
    snapshot.confidence = projection_confidence
    snapshot.evidence_coverage = projection_evidence
    snapshot.skipped_weight = max(0.0, projection_configured - projection_available)
    await session.flush()
    await publish_health_ranking(session, snapshot.repository_id, snapshot, score_projection)
    log.info("rescore_completed snapshot_id=%s score_config_digest=%s aggregates=%d", snapshot_id, digest, len(aggregates))
    return aggregates


__all__ = [
    "compare_health_snapshots",
    "load_health_snapshot_envelope",
    "rescore_health_snapshot",
    "save_health_envelope",
]
