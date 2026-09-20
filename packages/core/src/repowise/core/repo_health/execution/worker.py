"""Worker loop over the same LocalExecutor and AnalyzerTask contract."""

from __future__ import annotations

from typing import Protocol

from .local import LocalExecutor
from .queue import QueuePort
from .tasks import ExecutionOutcome


class ExecutionResultWriter(Protocol):
    async def persist(self, outcome: ExecutionOutcome) -> None: ...


class WorkerExecutor:
    """Claim, execute, persist-before-ack, and retry one queue task."""

    def __init__(
        self,
        queue: QueuePort,
        local_executor: LocalExecutor,
        result_writer: ExecutionResultWriter,
        *,
        worker_id: str,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._queue = queue
        self._local = local_executor
        self._writer = result_writer
        self._worker_id = worker_id
        self._retry_delay_seconds = retry_delay_seconds

    async def run_once(self) -> ExecutionOutcome | None:
        lease = await self._queue.claim(self._worker_id)
        if lease is None:
            return None
        outcome = await self._local.execute(lease.task)
        if outcome.retryable:
            await self._queue.retry(
                lease.task.task_id,
                self._worker_id,
                reason=outcome.failure_kind or "retryable_failure",
                delay_seconds=self._retry_delay_seconds,
            )
            return outcome
        await self._writer.persist(outcome)
        await self._queue.ack(lease.task.task_id, self._worker_id)
        return outcome


__all__ = ["ExecutionResultWriter", "WorkerExecutor"]
