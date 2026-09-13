"""REST route for the canonical persisted health read model."""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from repowise.core.persistence import crud
from repowise.server.deps import get_db_session
from repowise.server.schemas.code_health import CanonicalHealthReport

from ._router import router
from .canonical import build_canonical_health_report

log = logging.getLogger("api.health")


@router.get(
    "/api/repos/{repo_id}/health/canonical",
    response_model=CanonicalHealthReport,
)
async def canonical_health(
    repo_id: str,
    snapshot: str | None = Query(None, description="Persisted health snapshot id."),
    scope: str | None = Query(None, description="Exact persisted scope, e.g. all or production."),
    dimension: str | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    subject: str | None = Query(None),
    window: str | None = Query(None, description="ISO timestamp or duration such as 90d."),
    include_evidence: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return the exact persisted projection used by product surfaces."""
    if await crud.get_repository(session, repo_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        report = await build_canonical_health_report(
            session,
            repo_id,
            snapshot_id=snapshot,
            scope=scope,
            dimension=dimension,
            status=status,
            severity=severity,
            subject=subject,
            window=window,
            include_evidence=include_evidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if report is None:
        log.error(
            "canonical_health_not_found repository_id=%s snapshot_id=%s",
            repo_id,
            snapshot,
        )
        raise HTTPException(status_code=404, detail="Persisted health snapshot not found")
    return report
