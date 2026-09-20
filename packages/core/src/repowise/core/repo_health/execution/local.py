"""Failure-isolated local executor using the worker-compatible task contract."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from ..contracts.results import CategoryResult, CategoryStatus, Confidence, Coverage, Limitation
from .observability import ExecutionTelemetry
from .tasks import AnalyzerTask, ExecutionOutcome, ExecutionState

log = structlog.get_logger("repo_health.execution")


class RetryableExecutionError(RuntimeError):
    """Signal a transient provider/process failure safe to retry."""


class AnalyzerCallable(Protocol):
    def __call__(self, analyzer_input: Any) -> Any: ...


def _failure_result(task: AnalyzerTask, *, reason: str, kind: str) -> CategoryResult:
    return CategoryResult(
        analysis_id=task.analysis_id,
        analyzer_id=task.analyzer_id,
        analyzer_version=task.analyzer_version,
        category=task.category,
        status=CategoryStatus.ERROR,
        coverage=Coverage(status="unavailable", reason=reason),
        confidence=Confidence(value=0.0, level="unknown", reason=reason),
        limitations=(Limitation(code=kind, reason=reason, affected_scope=task.category.value),),
    )


class LocalExecutor:
    """Run one injected analyzer in-process with the same serialized boundary."""

    def __init__(self, factories: Mapping[str, AnalyzerCallable]) -> None:
        self._factories = dict(factories)
        self._semaphore = asyncio.Semaphore(6)
        self._telemetry: ExecutionTelemetry | None = None

    @classmethod
    def configured(
        cls,
        factories: Mapping[str, AnalyzerCallable],
        *,
        max_concurrency: int = 6,
        telemetry: ExecutionTelemetry | None = None,
    ) -> LocalExecutor:
        instance = cls(factories)
        instance._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        instance._telemetry = telemetry
        return instance

    async def execute(self, task: AnalyzerTask) -> ExecutionOutcome:
        async with self._semaphore:
            outcome = await self._execute(task)
        if self._telemetry is not None:
            self._telemetry.record(
                "repo_health_analyzer_finished",
                {
                    "analysis_id": task.analysis_id,
                    "task_id": task.task_id,
                    "trace_id": task.trace_id,
                    "analyzer_id": task.analyzer_id,
                    "attempt": task.attempt,
                    "state": outcome.state.value,
                    "status": outcome.result.status.value,
                    "retryable": outcome.retryable,
                    "failure_kind": outcome.failure_kind,
                },
            )
        return outcome

    async def _execute(self, task: AnalyzerTask) -> ExecutionOutcome:
        started = datetime.now(UTC)
        facts_size = len(task.input.facts.to_json().encode("utf-8"))
        observation_count = sum(
            len(group.observations)
            for group in (
                task.input.facts.git,
                task.input.facts.documentation,
                task.input.facts.issues,
                task.input.facts.cicd,
                task.input.facts.security,
                task.input.facts.code_health,
            )
        )
        if facts_size > task.resource_limits.max_bytes or observation_count > task.resource_limits.max_files:
            result = _failure_result(task, reason="resource limit exceeded", kind="other")
            return self._outcome(task, result, started, state=ExecutionState.FAILED, failure_kind="resource_limit")
        factory = self._factories.get(task.analyzer_id)
        if factory is None:
            result = _failure_result(task, reason="analyzer factory unavailable", kind="unsupported")
            return self._outcome(task, result, started, state=ExecutionState.FAILED, failure_kind="unsupported")
        if task.deadline_at is not None and datetime.now(UTC) >= task.deadline_at:
            result = _failure_result(task, reason="analysis deadline exceeded", kind="timeout")
            return self._outcome(task, result, started, state=ExecutionState.TIMEOUT, failure_kind="timeout")

        timeout = task.resource_limits.timeout_seconds
        if task.deadline_at is not None:
            timeout = min(timeout, max(0.001, (task.deadline_at - started).total_seconds()))
        try:
            value = await asyncio.wait_for(asyncio.to_thread(factory, task.input), timeout=timeout)
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(value, timeout=timeout)
            result = CategoryResult.model_validate(value.model_dump(mode="json"))
            if result.analysis_id != task.analysis_id or result.analyzer_id != task.analyzer_id:
                raise ValueError("factory returned a result for a different task")
            if result.category is not task.category:
                raise ValueError("factory returned a result for a different category")
            state = ExecutionState.COMPLETED if result.status is not CategoryStatus.ERROR else ExecutionState.FAILED
            return self._outcome(task, result, started, state=state)
        except TimeoutError:
            result = _failure_result(task, reason="analyzer execution timed out", kind="timeout")
            return self._outcome(task, result, started, state=ExecutionState.TIMEOUT, retryable=True, failure_kind="timeout")
        except RetryableExecutionError:
            result = _failure_result(task, reason="transient analyzer failure", kind="error")
            return self._outcome(task, result, started, state=ExecutionState.FAILED, retryable=True, failure_kind="transient")
        except Exception as exc:
            log.warning(
                "repo_health_analyzer_failed",
                analysis_id=task.analysis_id,
                task_id=task.task_id,
                analyzer_id=task.analyzer_id,
                attempt=task.attempt,
                error_type=type(exc).__name__,
                failure_kind="validation" if isinstance(exc, ValueError) else "error",
            )
            result = _failure_result(task, reason="analyzer execution failed", kind="error")
            return self._outcome(task, result, started, state=ExecutionState.FAILED, failure_kind="error")

    @staticmethod
    def _outcome(
        task: AnalyzerTask,
        result: CategoryResult,
        started: datetime,
        *,
        state: ExecutionState,
        retryable: bool = False,
        failure_kind: str | None = None,
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            task_id=task.task_id,
            analysis_id=task.analysis_id,
            state=state,
            result=result,
            attempt=task.attempt,
            retryable=retryable,
            failure_kind=failure_kind,
            started_at=started,
            finished_at=datetime.now(UTC),
        )


__all__ = ["LocalExecutor", "RetryableExecutionError"]
