"""Deployment/runtime contract for the single Repo Health worker boundary."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkerConfig(BaseModel):
    """Runtime config; the database URL is intentionally never task/log data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_backend: Literal["memory", "sql"] = "sql"
    database_url: str | None = None
    worker_id: str = Field(default="repo-health-worker", min_length=1, max_length=128)
    max_concurrency: int = Field(default=6, ge=1, le=256)
    visibility_timeout_seconds: float = Field(default=300.0, gt=0, le=86_400)
    shutdown_timeout_seconds: float = Field(default=30.0, gt=0, le=600)

    @field_validator("worker_id", mode="before")
    @classmethod
    def _safe_worker_id(cls, value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value.strip()):
            raise ValueError("worker_id must be a bounded identifier")
        return value.strip()

    @classmethod
    def from_env(cls) -> WorkerConfig:
        return cls(
            queue_backend=os.getenv("REPO_HEALTH_QUEUE_BACKEND", "sql").strip().lower(),
            database_url=os.getenv("REPO_HEALTH_DATABASE_URL"),
            worker_id=os.getenv("REPO_HEALTH_WORKER_ID", "repo-health-worker"),
            max_concurrency=int(os.getenv("REPO_HEALTH_MAX_CONCURRENCY", "6")),
            visibility_timeout_seconds=float(os.getenv("REPO_HEALTH_VISIBILITY_TIMEOUT", "300")),
            shutdown_timeout_seconds=float(os.getenv("REPO_HEALTH_SHUTDOWN_TIMEOUT", "30")),
        )

    def redacted(self) -> dict[str, object]:
        return {
            "queue_backend": self.queue_backend,
            "database_configured": bool(self.database_url),
            "worker_id": self.worker_id,
            "max_concurrency": self.max_concurrency,
            "visibility_timeout_seconds": self.visibility_timeout_seconds,
            "shutdown_timeout_seconds": self.shutdown_timeout_seconds,
        }


class WorkerReadiness(BaseModel):
    """Safe readiness projection; it never exposes credentials or provider payloads."""

    ready: bool
    process: Literal["ok", "failed"] = "ok"
    database: Literal["ok", "unavailable", "not_required"]
    queue: Literal["ok", "unavailable"]
    reason: str | None = None


def readiness(
    config: WorkerConfig,
    *,
    database_available: bool,
    queue_available: bool,
) -> WorkerReadiness:
    database_state = (
        "ok"
        if database_available
        else "not_required"
        if config.queue_backend == "memory"
        else "unavailable"
    )
    ready = queue_available and database_state in {"ok", "not_required"}
    return WorkerReadiness(
        ready=ready,
        database=database_state,
        queue="ok" if queue_available else "unavailable",
        reason=None if ready else "required worker dependency unavailable",
    )


__all__ = ["WorkerConfig", "WorkerReadiness", "readiness"]
