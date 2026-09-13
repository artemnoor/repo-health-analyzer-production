"""Unauthenticated, public-safe repository-health ranking endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from repowise.core.analysis.health.ranking_projection import normalize_filter
from repowise.core.persistence import crud
from repowise.server.deps import get_db_session
from repowise.server.schemas.health_ranking import (
    HealthRankingCompareResponse,
    HealthRankingEntryResponse,
    HealthRankingResponse,
    HealthRankingTrendResponse,
)

log = structlog.get_logger("server.public_health")

router = APIRouter(prefix="/api/health/ranking", tags=["public-health"])


@router.get("", response_model=HealthRankingResponse)
async def get_public_health_ranking(
    *,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    band: str | None = Query(None),
    dimension: str | None = Query(None),
    language: str | None = Query(None),
    status: str | None = Query(None),
    stale: bool | None = Query(None),
    eligible: bool | None = Query(None),
    include_ineligible: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
) -> HealthRankingResponse:
    """Return only materialized public ranking rows, never raw health data."""
    effective_eligible = eligible if eligible is not None else (None if include_ineligible else True)
    try:
        ranking_filter = normalize_filter(
            band=band,
            dimension=dimension,
            language=language,
            status=status,
            stale=stale,
            eligible=effective_eligible,
        )
        rows, total = await crud.list_health_ranking(
            session,
            ranking_filter=ranking_filter,
            page=page,
            limit=limit,
            include_ineligible=include_ineligible,
        )
        facets = await crud.list_health_ranking_facets(
            session,
            include_ineligible=include_ineligible,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log.info(
        "public_ranking_read",
        page=page,
        limit=limit,
        rows=len(rows),
        total=total,
        facet_count=sum(len(values) for values in facets.values()),
    )
    return HealthRankingResponse(
        items=[HealthRankingEntryResponse.model_validate(row) for row in rows],
        page=page,
        limit=limit,
        total=total,
        facets=facets,
        generated_at=datetime.now(UTC),
    )


@router.get("/compare", response_model=HealthRankingCompareResponse)
async def compare_public_health(
    repo_ids: str = Query(..., description="Comma-separated repository IDs; maximum four."),
    session: AsyncSession = Depends(get_db_session),
) -> HealthRankingCompareResponse:
    """Compare up to four eligible public rows using one score policy."""
    requested = [item.strip() for item in repo_ids.split(",") if item.strip()]
    if not requested:
        raise HTTPException(status_code=422, detail="At least one repository ID is required")
    truncated = len(requested) > 4
    selected = requested[:4]
    rows, _ = await crud.list_health_ranking(
        session,
        ranking_filter=normalize_filter(eligible=True),
        page=1,
        limit=4,
        include_ineligible=False,
        repository_ids=selected,
    )
    entries = [HealthRankingEntryResponse.model_validate(row) for row in rows]
    dimensions: dict[str, dict[str, float | None]] = {}
    for entry in entries:
        for dimension, value in entry.dimensions.items():
            dimensions.setdefault(dimension, {})[entry.repository_id] = value
    digests = sorted({entry.score_config_digest for entry in entries})
    return HealthRankingCompareResponse(
        items=entries,
        dimensions=dimensions,
        score_config_digests=digests,
        truncated=truncated,
        generated_at=datetime.now(UTC),
    )


@router.get("/trend", response_model=HealthRankingTrendResponse)
async def get_public_health_trend(
    repo_ids: str = Query(..., description="Comma-separated repository IDs; maximum eight."),
    limit: int = Query(12, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
) -> HealthRankingTrendResponse:
    """Return historical scores for a bounded set of currently eligible rows."""
    requested = [item.strip() for item in repo_ids.split(",") if item.strip()]
    if not requested:
        raise HTTPException(status_code=422, detail="At least one repository ID is required")
    truncated = len(requested) > 8
    rows = await crud.list_health_ranking_trend(session, requested[:8], limit=limit)
    log.info(
        "public_ranking_trend_read",
        repositories=len(rows),
        limit=limit,
        truncated=truncated,
    )
    return HealthRankingTrendResponse(items=rows, limit=limit, generated_at=datetime.now(UTC))


__all__ = ["router"]
