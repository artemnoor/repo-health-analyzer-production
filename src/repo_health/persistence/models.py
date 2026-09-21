"""Small persistence records for repositories, analyses and analyzer tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..contracts.execution import AnalyzerTask, ExecutionOutcome
from ..contracts.requests import RepositoryRef
from ..contracts.results import AnalysisEnvelope, AnalysisState


class PersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RepositoryRecord(PersistenceModel):
    repository: RepositoryRef
    created_at: datetime
    updated_at: datetime


class AnalysisRecord(PersistenceModel):
    analysis_id: str
    repository_id: str
    idempotency_key: str
    state: AnalysisState
    envelope: AnalysisEnvelope
    created_at: datetime
    updated_at: datetime


class AnalyzerTaskRecord(PersistenceModel):
    task_id: str
    analysis_id: str
    analyzer_id: str
    status: Literal["queued", "running", "completed", "retry", "failed"]
    attempt: int = Field(ge=1)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    task: AnalyzerTask
    outcome: ExecutionOutcome | None = None
    available_at: datetime
    updated_at: datetime


class AnalysisSummaryProjection(PersistenceModel):
    analysis_id: str
    repository_id: str
    state: AnalysisState
    overall_score: float | None = None
    score_status: str | None = None
    category_count: int = 0
    limitation_count: int = 0
    updated_at: datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = ["AnalysisRecord", "AnalysisSummaryProjection", "AnalyzerTaskRecord", "RepositoryRecord", "now_utc"]
