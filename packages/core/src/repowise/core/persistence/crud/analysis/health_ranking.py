"""Materialized, public-safe repository-health ranking CRUD."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....analysis.health.ranking_projection import (
    EligibilityDecision,
    RankingCandidate,
    RankingFilter,
    RankingPolicy,
    band_for_score,
    evaluate_eligibility,
    grade_for_score,
    rank_candidates,
)
from ...models import (
    HealthScoreProjection,
    Repository,
    RepositoryHealthRankingEntry,
    RepositoryHealthSnapshot,
    _new_uuid,
    _now_utc,
)

log = structlog.get_logger("health.ranking.persistence")


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _json_list(value: str | None) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []


def _languages(repo: Repository) -> tuple[str, ...]:
    settings = _json_object(repo.settings_json)
    values = settings.get("languages") or settings.get("language") or ()
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({str(value).lower() for value in values if str(value).strip()}))


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _candidate(
    repo: Repository,
    snapshot: RepositoryHealthSnapshot,
    projection: HealthScoreProjection,
    *,
    languages: Iterable[str] | None = None,
) -> RankingCandidate:
    dimensions = _json_object(projection.dimensions_json)
    normalized_dimensions = {
        str(key): _finite_float(value)
        for key, value in dimensions.items()
    }
    language_values = tuple(sorted({str(value).lower() for value in (languages or _languages(repo))}))
    return RankingCandidate(
        repository_id=repo.id,
        name=repo.name,
        url=repo.url,
        visibility=repo.visibility,
        snapshot_id=snapshot.id,
        score_config_digest=projection.score_config_digest,
        overall_score=projection.overall_score,
        status=projection.status,
        dimensions=normalized_dimensions,
        languages=language_values,
        confidence=projection.confidence,
        coverage=projection.coverage,
        evidence_coverage=projection.evidence_coverage,
        analyzed_at=snapshot.analyzed_at,
        stale_after_ts=snapshot.stale_after_ts,
        mode=snapshot.mode,
        score_delta=None,
        eligible=projection.overall_score is not None,
        eligibility_reason=None,
    )


def _public_row(candidate: RankingCandidate, decision: EligibilityDecision) -> dict[str, Any]:
    """Serialize only fields allowed by the public ranking contract."""
    stale = decision.stale
    overall_score = (
        candidate.overall_score
        if candidate.overall_score is not None and math.isfinite(candidate.overall_score)
        else None
    )
    return {
        "repository_id": candidate.repository_id,
        "name": candidate.name,
        "url": candidate.url,
        "snapshot_id": candidate.snapshot_id,
        "score_config_digest": candidate.score_config_digest,
        "overall_score": overall_score,
        "band": band_for_score(overall_score),
        "grade": grade_for_score(overall_score),
        "status": candidate.status,
        "dimensions": dict(candidate.dimensions),
        "languages": list(candidate.languages),
        "confidence": candidate.confidence,
        "coverage": candidate.coverage,
        "evidence_coverage": candidate.evidence_coverage,
        "analyzed_at": candidate.analyzed_at.isoformat() if candidate.analyzed_at else None,
        "stale": stale,
        "eligible": decision.eligible,
        "eligibility_reason": decision.reason,
        "score_delta": _finite_float(candidate.score_delta),
    }


async def publish_health_ranking(
    session: AsyncSession,
    repository_id: str,
    snapshot: RepositoryHealthSnapshot,
    projection: HealthScoreProjection,
    *,
    languages: Iterable[str] | None = None,
    policy: RankingPolicy | None = None,
    now: datetime | None = None,
) -> RepositoryHealthRankingEntry:
    """Upsert the ranking row after a canonical snapshot commits."""
    repo = await session.get(Repository, repository_id)
    if repo is None:
        raise LookupError(f"Repository not found: {repository_id}")
    existing_result = await session.execute(
        select(RepositoryHealthRankingEntry).where(
            RepositoryHealthRankingEntry.repository_id == repository_id
        )
    )
    entry = existing_result.scalar_one_or_none()
    candidate = _candidate(repo, snapshot, projection, languages=languages)
    decision = evaluate_eligibility(candidate, now=now, policy=policy)
    previous_score = entry.overall_score if entry is not None else None
    score_delta = (
        candidate.overall_score - previous_score
        if candidate.overall_score is not None and previous_score is not None
        else None
    )
    if entry is None:
        entry = RepositoryHealthRankingEntry(id=_new_uuid(), repository_id=repository_id)
        session.add(entry)
    entry.snapshot_id = snapshot.id
    entry.score_config_digest = projection.score_config_digest
    entry.overall_score = candidate.overall_score
    entry.grade = grade_for_score(candidate.overall_score)
    entry.status = candidate.status
    entry.mode = candidate.mode
    entry.dimensions_json = json.dumps(dict(candidate.dimensions), sort_keys=True)
    entry.languages_json = json.dumps(list(candidate.languages), sort_keys=True)
    entry.confidence = candidate.confidence
    entry.coverage = candidate.coverage
    entry.evidence_coverage = candidate.evidence_coverage
    entry.analyzed_at = snapshot.analyzed_at
    entry.stale_after_ts = snapshot.stale_after_ts
    entry.score_delta = score_delta
    entry.eligible = decision.eligible
    entry.eligibility_reason = decision.reason
    entry.updated_at = _now_utc()
    await session.flush()
    log.info(
        "ranking_projection_published",
        repository_id=repository_id,
        eligible=decision.eligible,
        reason=decision.reason,
    )
    return entry


async def rebuild_health_ranking(
    session: AsyncSession,
    *,
    policy: RankingPolicy | None = None,
    now: datetime | None = None,
) -> int:
    """Rebuild current rows idempotently from the latest snapshot per repo."""
    repos_result = await session.execute(select(Repository).order_by(Repository.id))
    count = 0
    for repo in repos_result.scalars().all():
        snapshot_result = await session.execute(
            select(RepositoryHealthSnapshot)
            .where(RepositoryHealthSnapshot.repository_id == repo.id)
            .order_by(RepositoryHealthSnapshot.created_at.desc(), RepositoryHealthSnapshot.id.desc())
            .limit(1)
        )
        snapshot = snapshot_result.scalar_one_or_none()
        if snapshot is None:
            continue
        projection_result = await session.execute(
            select(HealthScoreProjection)
            .where(
                HealthScoreProjection.snapshot_id == snapshot.id,
                HealthScoreProjection.score_config_digest == snapshot.score_config_digest,
            )
            .order_by(HealthScoreProjection.created_at.desc(), HealthScoreProjection.id.desc())
            .limit(1)
        )
        projection = projection_result.scalar_one_or_none()
        if projection is None:
            continue
        await publish_health_ranking(session, repo.id, snapshot, projection, policy=policy, now=now)
        count += 1
    log.info("ranking_projection_rebuilt", count=count)
    return count


async def list_health_ranking(
    session: AsyncSession,
    *,
    ranking_filter: RankingFilter | None = None,
    page: int = 1,
    limit: int = 50,
    include_ineligible: bool = False,
    repository_ids: Iterable[str] | None = None,
    policy: RankingPolicy | None = None,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Read materialized rows and apply deterministic pure ranking logic."""
    query = (
        select(Repository, RepositoryHealthRankingEntry)
        .join(
            RepositoryHealthRankingEntry,
            RepositoryHealthRankingEntry.repository_id == Repository.id,
        )
        .where(Repository.visibility == "public")
    )
    if not include_ineligible:
        query = query.where(RepositoryHealthRankingEntry.eligible.is_(True))
    if repository_ids is not None:
        ids = tuple(repository_ids)
        if not ids:
            return [], 0
        query = query.where(Repository.id.in_(ids))
    result = await session.execute(query)
    candidates: list[RankingCandidate] = []
    decisions: dict[str, EligibilityDecision] = {}
    for repo, entry in result.all():
        dimensions = _json_object(entry.dimensions_json)
        normalized_dimensions = {
            str(key): _finite_float(value)
            for key, value in dimensions.items()
        }
        candidate = RankingCandidate(
            repository_id=repo.id,
            name=repo.name,
            url=repo.url,
            visibility=repo.visibility,
            snapshot_id=entry.snapshot_id,
            score_config_digest=entry.score_config_digest,
            overall_score=entry.overall_score,
            status=entry.status,
            dimensions=normalized_dimensions,
            languages=tuple(_json_list(entry.languages_json)),
            confidence=entry.confidence,
            coverage=entry.coverage,
            evidence_coverage=entry.evidence_coverage,
            analyzed_at=entry.analyzed_at,
            stale_after_ts=entry.stale_after_ts,
            mode=entry.mode,
            score_delta=entry.score_delta,
            eligible=entry.eligible,
            eligibility_reason=entry.eligibility_reason,
        )
        decision = evaluate_eligibility(candidate, now=now, policy=policy)
        candidate = replace(
            candidate,
            eligible=decision.eligible,
            eligibility_reason=decision.reason,
        )
        candidates.append(candidate)
        decisions[candidate.repository_id] = decision
    rows, total = rank_candidates(
        candidates,
        ranking_filter=(
            RankingFilter(
                band=ranking_filter.band,
                dimension=ranking_filter.dimension,
                language=ranking_filter.language,
                status=ranking_filter.status,
                stale=ranking_filter.stale,
                eligible=None,
            )
            if include_ineligible and ranking_filter is None
            else ranking_filter
        ),
        page=page,
        limit=limit,
        now=now,
        policy=policy,
    )
    return [_public_row(row, decisions[row.repository_id]) for row in rows], total


def _decode_facet_json(
    value: str | None,
    *,
    repository_id: str,
    field_name: str,
    expected_type: type[dict] | type[list],
) -> dict[str, Any] | list[Any]:
    if value is None:
        return {} if expected_type is dict else []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        log.warning(
            "health_ranking_facet_json_invalid",
            repository_id=repository_id,
            field=field_name,
        )
        return {} if expected_type is dict else []
    if not isinstance(decoded, expected_type):
        log.warning(
            "health_ranking_facet_json_wrong_type",
            repository_id=repository_id,
            field=field_name,
        )
        return {} if expected_type is dict else []
    return decoded


def _stable_facet_name(value: object) -> str | None:
    normalized = str(value).strip().lower()
    return normalized or None


async def list_health_ranking_facets(
    session: AsyncSession,
    *,
    include_ineligible: bool = False,
) -> dict[str, list[str]]:
    """Return deterministic, public-safe filter values independent of page size."""
    query = (
        select(
            Repository.id,
            RepositoryHealthRankingEntry.dimensions_json,
            RepositoryHealthRankingEntry.languages_json,
            RepositoryHealthRankingEntry.status,
        )
        .join(
            RepositoryHealthRankingEntry,
            RepositoryHealthRankingEntry.repository_id == Repository.id,
        )
        .where(Repository.visibility == "public")
    )
    if not include_ineligible:
        query = query.where(RepositoryHealthRankingEntry.eligible.is_(True))

    result = await session.execute(query)
    dimensions: set[str] = set()
    languages: set[str] = set()
    statuses: set[str] = set()
    for repository_id, dimensions_json, languages_json, status in result.all():
        raw_dimensions = _decode_facet_json(
            dimensions_json,
            repository_id=repository_id,
            field_name="dimensions_json",
            expected_type=dict,
        )
        for value in raw_dimensions:
            normalized = _stable_facet_name(value)
            if normalized:
                dimensions.add(normalized)

        raw_languages = _decode_facet_json(
            languages_json,
            repository_id=repository_id,
            field_name="languages_json",
            expected_type=list,
        )
        for value in raw_languages:
            normalized = _stable_facet_name(value)
            if normalized:
                languages.add(normalized)

        normalized_status = _stable_facet_name(status)
        if normalized_status:
            statuses.add(normalized_status)

    facets = {
        "dimensions": sorted(dimensions),
        "languages": sorted(languages),
        "statuses": sorted(statuses),
    }
    log.info(
        "health_ranking_facets_read",
        include_ineligible=include_ineligible,
        dimensions=len(facets["dimensions"]),
        languages=len(facets["languages"]),
        statuses=len(facets["statuses"]),
    )
    return facets


async def list_health_ranking_trend(
    session: AsyncSession,
    repository_ids: Iterable[str],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Return bounded, public-safe score history for eligible public rows."""
    ids = tuple(dict.fromkeys(repository_ids))[:8]
    if not ids:
        return []
    bounded_limit = max(1, min(limit, 50))
    current_result = await session.execute(
        select(Repository.id)
        .join(
            RepositoryHealthRankingEntry,
            RepositoryHealthRankingEntry.repository_id == Repository.id,
        )
        .where(
            Repository.id.in_(ids),
            Repository.visibility == "public",
            RepositoryHealthRankingEntry.eligible.is_(True),
        )
    )
    eligible_ids = set(current_result.scalars().all())
    if not eligible_ids:
        return []
    result = await session.execute(
        select(Repository, RepositoryHealthSnapshot, HealthScoreProjection)
        .join(
            RepositoryHealthSnapshot,
            RepositoryHealthSnapshot.repository_id == Repository.id,
        )
        .join(
            HealthScoreProjection,
            and_(
                HealthScoreProjection.snapshot_id == RepositoryHealthSnapshot.id,
                HealthScoreProjection.score_config_digest == RepositoryHealthSnapshot.score_config_digest,
            ),
        )
        .where(
            Repository.id.in_(eligible_ids),
            Repository.visibility == "public",
        )
        .order_by(
            Repository.id.asc(),
            RepositoryHealthSnapshot.analyzed_at.asc(),
            RepositoryHealthSnapshot.id.asc(),
        )
    )
    grouped: dict[str, dict[str, Any]] = {
        repository_id: {"repository_id": repository_id, "name": "", "points": []}
        for repository_id in eligible_ids
    }
    for repo, snapshot, projection in result.all():
        series = grouped[repo.id]
        series["name"] = repo.name
        series["points"].append(
            {
                "snapshot_id": snapshot.id,
                "score_config_digest": projection.score_config_digest,
                "overall_score": _finite_float(projection.overall_score),
                "band": band_for_score(_finite_float(projection.overall_score)),
                "grade": grade_for_score(_finite_float(projection.overall_score)),
                "status": projection.status,
                "analyzed_at": snapshot.analyzed_at.isoformat() if snapshot.analyzed_at else None,
            }
        )
    return [
        {**series, "points": series["points"][-bounded_limit:]}
        for repository_id, series in sorted(grouped.items())
        if series["points"]
    ]


__all__ = [
    "list_health_ranking",
    "list_health_ranking_facets",
    "list_health_ranking_trend",
    "publish_health_ranking",
    "rebuild_health_ranking",
]
