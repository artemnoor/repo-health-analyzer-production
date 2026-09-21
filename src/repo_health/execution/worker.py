"""One-process worker loop over the SQLite task boundary."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog

from ..contracts.execution import AnalyzerTask, ExecutionOutcome
from ..persistence.ports import PersistencePort
from .local import LocalExecutor

log = structlog.get_logger("repo_health.execution.worker")


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

    async def execute_many(self, tasks: Sequence[AnalyzerTask]) -> tuple[ExecutionOutcome, ...]:
        """Execute a bounded batch through the durable queue and return final outcomes."""

        ordered = tuple(sorted(tasks, key=lambda item: item.analyzer_id))
        pending = {task.task_id: task for task in ordered}
        outcomes: dict[str, ExecutionOutcome] = {}
        for task in ordered:
            self.enqueue(task)
        log.info(
            "worker_batch_started",
            worker_id=self.worker_id,
            analysis_id=ordered[0].analysis_id if ordered else None,
            task_count=len(ordered),
        )
        max_rounds = max(1, len(ordered) * self.max_attempts)
        for _ in range(max_rounds):
            if not pending:
                break
            outcome = await self.run_once()
            if outcome is None:
                break
            if outcome.task_id not in pending:
                continue
            if outcome.retryable and outcome.attempt < self.max_attempts:
                continue
            outcomes[outcome.task_id] = outcome
            pending.pop(outcome.task_id, None)
        if pending:
            missing = tuple(sorted(pending))
            log.error(
                "worker_batch_incomplete",
                worker_id=self.worker_id,
                analysis_id=ordered[0].analysis_id if ordered else None,
                missing_task_ids=missing,
            )
            raise RuntimeError(f"worker queue drained before tasks completed: {missing!r}")
        log.info(
            "worker_batch_finished",
            worker_id=self.worker_id,
            analysis_id=ordered[0].analysis_id if ordered else None,
            task_count=len(outcomes),
        )
        return tuple(outcomes[task.task_id] for task in ordered)

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
                worker_id=self.worker_id,
                retry=True,
                error=outcome.failure_kind or "retryable",
                available_at=datetime.now(UTC) + timedelta(seconds=min(60, 2**claimed.attempt)),
            )
        else:
            self.persistence.complete_task(outcome, worker_id=self.worker_id)
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
