"""Versioned task and outcome contracts shared by local and worker modes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..analyzers.registry import CANONICAL_ANALYZER_IDS
from ..contracts.requests import CONTRACT_SCHEMA_VERSION, canonical_json
from ..contracts.results import (
    AnalyzerInput,
    CategoryResult,
    HealthCategory,
)
from ..contracts.results import _ContractBase as ContractBase


class ExecutionState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ResourceLimits(ContractBase):
    """Deterministic guardrails passed to a worker, not hidden globals."""

    max_files: int = Field(default=100_000, ge=1, le=10_000_000)
    max_bytes: int = Field(default=2_000_000_000, ge=1, le=100_000_000_000)
    max_commits: int = Field(default=100_000, ge=1, le=10_000_000)
    max_pages: int = Field(default=10_000, ge=1, le=1_000_000)
    max_output_bytes: int = Field(default=16_777_216, ge=1024, le=1_073_741_824)
    timeout_seconds: float = Field(default=300.0, gt=0, le=86_400)


class AnalyzerTask(ContractBase):
    """One idempotent analyzer invocation; payload is queue/process safe JSON."""

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    analysis_id: str = Field(min_length=1, max_length=128)
    task_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    analyzer_id: str = Field(min_length=1, max_length=128)
    analyzer_version: str = Field(min_length=1, max_length=128)
    category: HealthCategory
    input: AnalyzerInput
    facts_digest: str = Field(min_length=8, max_length=128)
    policy_digest: str = Field(min_length=8, max_length=128)
    attempt: int = Field(default=1, ge=1, le=100)
    deadline_at: datetime | None = None
    trace_id: str | None = Field(default=None, max_length=128)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)

    _canonical_ids = field_validator("analyzer_id", mode="before")(
        lambda value: value.strip().lower() if isinstance(value, str) else value
    )

    @model_validator(mode="after")
    def _task_is_consistent(self) -> AnalyzerTask:
        if self.analyzer_id not in CANONICAL_ANALYZER_IDS:
            raise ValueError(f"unknown canonical analyzer: {self.analyzer_id}")
        if self.input.analysis_id != self.analysis_id:
            raise ValueError("task and analyzer input must use the same analysis_id")
        if self.input.analyzer_id != self.analyzer_id:
            raise ValueError("task and analyzer input must use the same analyzer_id")
        if self.input.analyzer_version != self.analyzer_version:
            raise ValueError("task and analyzer input must use the same analyzer_version")
        if self.input.facts_digest != self.facts_digest:
            raise ValueError("task facts_digest must match AnalyzerInput")
        if self.input.policy_digest != self.policy_digest:
            raise ValueError("task policy_digest must match AnalyzerInput")
        if self.deadline_at is not None:
            deadline = self.deadline_at.astimezone(UTC)
            object.__setattr__(self, "deadline_at", deadline)
        if self.task_id is None:
            payload = {
                "analysis_id": self.analysis_id,
                "analyzer_id": self.analyzer_id,
                "analyzer_version": self.analyzer_version,
                "facts_digest": self.facts_digest,
                "policy_digest": self.policy_digest,
            }
            derived = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:32]
            object.__setattr__(self, "task_id", f"task-{derived}")
        if self.idempotency_key is None:
            object.__setattr__(self, "idempotency_key", self.task_id)
        if self.trace_id is None:
            object.__setattr__(self, "trace_id", f"trace-{self.analysis_id}")
        return self


class ExecutionOutcome(ContractBase):
    """Validated analyzer result plus safe execution lifecycle metadata."""

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    task_id: str
    analysis_id: str
    state: ExecutionState
    result: CategoryResult
    attempt: int = Field(ge=1)
    retryable: bool = False
    failure_kind: str | None = Field(default=None, max_length=128)
    started_at: datetime
    finished_at: datetime

    @model_validator(mode="after")
    def _outcome_is_consistent(self) -> ExecutionOutcome:
        if self.result.analysis_id != self.analysis_id:
            raise ValueError("execution result and outcome must use the same analysis_id")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be after started_at")
        if self.state is ExecutionState.TIMEOUT and not self.retryable:
            raise ValueError("timeout outcomes must be retryable")
        return self


__all__ = ["AnalyzerTask", "ExecutionOutcome", "ExecutionState", "ResourceLimits"]
