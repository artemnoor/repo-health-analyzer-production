"""Transport-neutral read DTOs shared by API, MCP and CLI adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..contracts.requests import CONTRACT_SCHEMA_VERSION
from ..contracts.results import AnalysisState, AnalysisStatus, RepoHealthResult


class AnalysisStatusProjection(BaseModel):
    """Stable lifecycle DTO; it deliberately contains no queue implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    analysis_id: str
    state: AnalysisState
    completed_analyzer_ids: tuple[str, ...] = ()
    failed_analyzer_ids: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=1000)

    @classmethod
    def from_contract(cls, status: AnalysisStatus) -> AnalysisStatusProjection:
        return cls.model_validate(status.model_dump(mode="python"))


class RepoHealthProjection(BaseModel):
    """Stable repository result projection for all inbound product surfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    analysis_id: str
    repository_id: str
    status: AnalysisStatusProjection
    overall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    score_before_caps: float | None = Field(default=None, ge=0.0, le=100.0)
    score_engine_version: str
    policy_digest: str | None = None
    score_config_digest: str | None = None
    presentation_state: Literal["SCORE", "PROVISIONAL_SCORE", "INSUFFICIENT_DATA"]
    coverage: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    coverage_k: float = Field(ge=0.0, le=1.0)
    applied_caps: tuple[dict[str, Any], ...] = ()
    limitations: tuple[dict[str, Any], ...] = ()
    score_status: Literal["pass", "warn", "fail", "inconclusive"]
    categories: dict[str, dict[str, Any] | None]

    @classmethod
    def from_contract(cls, result: RepoHealthResult) -> RepoHealthProjection:
        categories = {
            name: getattr(result, name).model_dump(mode="json") if getattr(result, name) else None
            for name in ("documentation", "activity", "issues", "cicd", "security", "code_health")
        }
        return cls(
            analysis_id=result.analysis_id,
            repository_id=result.repository.repository_id,
            status=AnalysisStatusProjection.from_contract(result.status),
            overall_score=result.overall_score,
            score_before_caps=result.score_before_caps,
            score_engine_version=result.score_engine_version,
            policy_digest=result.policy_digest,
            score_config_digest=result.score_config_digest,
            presentation_state=result.presentation_state,
            coverage=result.coverage,
            confidence=result.confidence,
            evidence_coverage=result.evidence_coverage,
            coverage_k=result.coverage_k,
            applied_caps=result.applied_caps,
            limitations=tuple(item.model_dump(mode="json") for item in result.limitations),
            score_status=result.score_status,
            categories=categories,
        )


__all__ = ["AnalysisStatusProjection", "RepoHealthProjection"]
