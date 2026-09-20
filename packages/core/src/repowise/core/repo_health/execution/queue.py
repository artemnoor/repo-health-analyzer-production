"""Replaceable queue port with in-memory and SQL-backed implementations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...persistence.models import RepoHealthTaskRecord
from ..contracts.requests import canonical_json
from ..contracts.results import _ContractBase as ContractBase
from .tasks import AnalyzerTask


class QueueConflictError(RuntimeError):
    """Raised when a task or idempotency key is reused with different content."""


class QueueLease(ContractBase):
    task: AnalyzerTask
    worker_id: str = Field(min_length=1, max_length=128)
    leased_until: datetime
    attempt: int = Field(ge=1)


class QueuePort(Protocol):
    async def publish(self, task: AnalyzerTask, *, max_attempts: int = 3) -> AnalyzerTask: ...

    async def claim(self, worker_id: str, *, visibility_timeout: float = 300.0) -> QueueLease | None: ...

    async def ack(self, task_id: str, worker_id: str) -> None: ...

    async def retry(self, task_id: str, worker_id: str, *, reason: str, delay_seconds: float) -> None: ...

    async def dead_letter(self, task_id: str, worker_id: str, *, reason: str) -> None: ...


class InMemoryQueue:
    """Deterministic queue for local development and contract tests."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, object]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, task: AnalyzerTask, *, max_attempts: int = 3) -> AnalyzerTask:
        async with self._lock:
            existing = self._rows.get(task.task_id)
            if existing is not None:
                if existing["payload"] != canonical_json(task):
                    raise QueueConflictError("task_id already belongs to different content")
                return task
            for row in self._rows.values():
                if row["idempotency_key"] == task.idempotency_key:
                    if row["payload"] != canonical_json(task):
                        raise QueueConflictError("idempotency key already belongs to different content")
                    return task
            self._rows[task.task_id] = {
                "payload": canonical_json(task),
                "idempotency_key": task.idempotency_key,
                "status": "pending",
                "available_at": datetime.now(UTC),
                "lease_until": None,
                "worker_id": None,
                "attempt": task.attempt,
                "max_attempts": max(1, max_attempts),
            }
            return task

    async def claim(self, worker_id: str, *, visibility_timeout: float = 300.0) -> QueueLease | None:
        now = datetime.now(UTC)
        async with self._lock:
            for _task_id, row in sorted(self._rows.items()):
                lease_until = row["lease_until"]
                if row["status"] == "dead" or (
                    row["status"] == "leased" and isinstance(lease_until, datetime) and lease_until > now
                ):
                    continue
                if row["status"] not in {"pending", "leased"} or row["available_at"] > now:
                    continue
                task = AnalyzerTask.model_validate_json(str(row["payload"]))
                row["status"] = "leased"
                row["worker_id"] = worker_id
                row["lease_until"] = now + timedelta(seconds=max(0.001, visibility_timeout))
                return QueueLease(
                    task=task,
                    worker_id=worker_id,
                    leased_until=row["lease_until"],
                    attempt=int(row["attempt"]),
                )
        return None

    async def ack(self, task_id: str, worker_id: str) -> None:
        async with self._lock:
            row = self._owned(task_id, worker_id)
            row["status"] = "acked"
            row["lease_until"] = None

    async def retry(self, task_id: str, worker_id: str, *, reason: str, delay_seconds: float) -> None:
        async with self._lock:
            row = self._owned(task_id, worker_id)
            task = AnalyzerTask.model_validate_json(str(row["payload"]))
            if int(row["attempt"]) >= int(row["max_attempts"]):
                row["status"] = "dead"
            else:
                next_task = task.model_copy(update={"attempt": task.attempt + 1})
                row["payload"] = canonical_json(next_task)
                row["attempt"] = next_task.attempt
                row["status"] = "pending"
                row["available_at"] = datetime.now(UTC) + timedelta(seconds=max(0.0, delay_seconds))
            row["last_error"] = reason
            row["lease_until"] = None
            row["worker_id"] = None

    async def dead_letter(self, task_id: str, worker_id: str, *, reason: str) -> None:
        async with self._lock:
            row = self._owned(task_id, worker_id)
            row["status"] = "dead"
            row["last_error"] = reason
            row["lease_until"] = None
            row["worker_id"] = None

    def _owned(self, task_id: str, worker_id: str) -> dict[str, object]:
        row = self._rows.get(task_id)
        if row is None or row["status"] != "leased" or row["worker_id"] != worker_id:
            raise RuntimeError("task is not leased by this worker")
        return row


class SqlQueue:
    """Database queue adapter with conditional claim and explicit lease state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, task: AnalyzerTask, *, max_attempts: int = 3) -> AnalyzerTask:
        existing = await self._session.get(RepoHealthTaskRecord, task.task_id)
        if existing is None:
            result = await self._session.execute(
                select(RepoHealthTaskRecord).where(
                    RepoHealthTaskRecord.analysis_id == task.analysis_id,
                    RepoHealthTaskRecord.idempotency_key == task.idempotency_key,
                )
            )
            existing = result.scalar_one_or_none()
        if existing is not None:
            if existing.payload_json != canonical_json(task):
                raise QueueConflictError("task_id or idempotency key already belongs to different content")
            return task
        self._session.add(
            RepoHealthTaskRecord(
                task_id=task.task_id,
                analysis_id=task.analysis_id,
                idempotency_key=task.idempotency_key,
                analyzer_id=task.analyzer_id,
                payload_json=canonical_json(task),
                status="pending",
                attempt=task.attempt,
                max_attempts=max(1, max_attempts),
                available_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.flush()
        return task

    async def claim(self, worker_id: str, *, visibility_timeout: float = 300.0) -> QueueLease | None:
        now = datetime.now(UTC)
        candidate_result = await self._session.execute(
            select(RepoHealthTaskRecord)
            .where(
                RepoHealthTaskRecord.available_at <= now,
                (
                    (RepoHealthTaskRecord.status == "pending")
                    | (
                        (RepoHealthTaskRecord.status == "leased")
                        & (
                            RepoHealthTaskRecord.lease_until.is_(None)
                            | (RepoHealthTaskRecord.lease_until <= now)
                        )
                    )
                ),
            )
            .order_by(RepoHealthTaskRecord.created_at, RepoHealthTaskRecord.task_id)
            .limit(1)
        )
        candidate = candidate_result.scalar_one_or_none()
        if candidate is None:
            return None
        if candidate.status == "leased" and candidate.lease_until is not None and candidate.lease_until > now:
            return None
        lease_until = now + timedelta(seconds=max(0.001, visibility_timeout))
        update_result = await self._session.execute(
            update(RepoHealthTaskRecord)
            .where(
                RepoHealthTaskRecord.task_id == candidate.task_id,
                RepoHealthTaskRecord.status.in_(("pending", "leased")),
                (RepoHealthTaskRecord.lease_until.is_(None) | (RepoHealthTaskRecord.lease_until <= now)),
            )
            .values(status="leased", worker_id=worker_id, lease_until=lease_until, updated_at=now)
        )
        if update_result.rowcount != 1:
            return None
        task = AnalyzerTask.model_validate_json(candidate.payload_json)
        return QueueLease(task=task, worker_id=worker_id, leased_until=lease_until, attempt=candidate.attempt)

    async def ack(self, task_id: str, worker_id: str) -> None:
        row = await self._owned(task_id, worker_id)
        row.status = "acked"
        row.lease_until = None
        row.worker_id = None
        row.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def retry(self, task_id: str, worker_id: str, *, reason: str, delay_seconds: float) -> None:
        row = await self._owned(task_id, worker_id)
        if row.attempt >= row.max_attempts:
            row.status = "dead"
        else:
            task = AnalyzerTask.model_validate_json(row.payload_json)
            next_task = task.model_copy(update={"attempt": task.attempt + 1})
            row.payload_json = canonical_json(next_task)
            row.attempt = next_task.attempt
            row.status = "pending"
            row.available_at = datetime.now(UTC) + timedelta(seconds=max(0.0, delay_seconds))
        row.last_error = reason
        row.lease_until = None
        row.worker_id = None
        row.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def dead_letter(self, task_id: str, worker_id: str, *, reason: str) -> None:
        row = await self._owned(task_id, worker_id)
        row.status = "dead"
        row.last_error = reason
        row.lease_until = None
        row.worker_id = None
        row.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def _owned(self, task_id: str, worker_id: str) -> RepoHealthTaskRecord:
        row = await self._session.get(RepoHealthTaskRecord, task_id)
        if row is None or row.status != "leased" or row.worker_id != worker_id:
            raise RuntimeError("task is not leased by this worker")
        return row


__all__ = ["InMemoryQueue", "QueueConflictError", "QueueLease", "QueuePort", "SqlQueue"]
