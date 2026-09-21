"""One-process worker loop over the SQLite task boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..persistence.ports import PersistencePort
from .local import LocalExecutor


class WorkerExecutor:
    def __init__(
        self,
        *,
        persistence: PersistencePort,
        local: LocalExecutor,
        worker_id: str,
        lease_seconds: float = 300.0,
        max_attempts: int = 3,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.persistence = persistence
        self.local = local
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def enqueue(self, task):
        return self.persistence.enqueue_task(task)

    async def run_once(self):
        claimed = self.persistence.claim_task(
            worker_id=self.worker_id, now=datetime.now(UTC), lease_seconds=self.lease_seconds
        )
        if claimed is None:
            return None
        outcome = await self.local.execute(claimed.task)
        if outcome.retryable and claimed.attempt < self.max_attempts:
            self.persistence.fail_task(
                claimed.task_id,
                retry=True,
                error=outcome.failure_kind or "retryable",
                available_at=datetime.now(UTC) + timedelta(seconds=min(60, 2**claimed.attempt)),
            )
        else:
            self.persistence.complete_task(outcome)
        return outcome

    def renew(self, task_id: str) -> bool:
        return self.persistence.renew_task(
            task_id=task_id,
            worker_id=self.worker_id,
            now=datetime.now(UTC),
            lease_seconds=self.lease_seconds,
        )

    async def run_until_empty(self, *, max_tasks: int | None = None) -> int:
        processed = 0
        while max_tasks is None or processed < max_tasks:
            outcome = await self.run_once()
            if outcome is None:
                break
            processed += 1
        return processed


__all__ = ["WorkerExecutor"]
