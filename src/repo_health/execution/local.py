"""Failure-isolated local executor shared with the worker envelope."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from ..contracts.execution import AnalyzerTask, ExecutionOutcome, ExecutionState
from ..contracts.results import CategoryResult, CategoryStatus, Confidence, Coverage, Limitation
from .observability import ExecutionTelemetry

log = structlog.get_logger("repo_health.execution.local")


class RetryableExecutionError(RuntimeError):
    """Signal a transient analyzer/tool error that may be retried."""


class AnalyzerCallable(Protocol):
    def __call__(self, analyzer_input: Any) -> Any: ...


def failure_result(task: AnalyzerTask, *, reason: str, kind: str) -> CategoryResult:
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
    def __init__(
        self,
        factories: Mapping[str, AnalyzerCallable],
        *,
        max_concurrency: int = 6,
        telemetry: ExecutionTelemetry | None = None,
        cache: dict[str, CategoryResult] | None = None,
    ) -> None:
        self._factories = dict(factories)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._telemetry = telemetry
        self._cache = cache if cache is not None else {}

    async def execute(self, task: AnalyzerTask) -> ExecutionOutcome:
        async with self._semaphore:
            outcome = await self._execute(task)
        self._record(
            "repo_health_analyzer_finished",
            {
                "analysis_id": task.analysis_id,
                "task_id": task.task_id,
                "analyzer_id": task.analyzer_id,
                "attempt": task.attempt,
                "state": outcome.state.value,
                "failure_kind": outcome.failure_kind,
            },
        )
        return outcome

    async def execute_many(self, tasks: Sequence[AnalyzerTask]) -> tuple[ExecutionOutcome, ...]:
        ordered = tuple(sorted(tasks, key=lambda item: item.analyzer_id))
        outcomes = await asyncio.gather(*(self.execute(task) for task in ordered), return_exceptions=True)
        safe: list[ExecutionOutcome] = []
        for task, outcome in zip(ordered, outcomes, strict=True):
            if isinstance(outcome, ExecutionOutcome):
                safe.append(outcome)
            else:
                safe.append(
                    self._outcome(
                        task,
                        failure_result(task, reason="executor failed before task result", kind="executor_error"),
                        datetime.now(UTC),
                        state=ExecutionState.FAILED,
                        failure_kind="executor_error",
                    )
                )
        return tuple(safe)

    async def _execute(self, task: AnalyzerTask) -> ExecutionOutcome:
        started = datetime.now(UTC)
        key = task.digest()
        cached = self._cache.get(key)
        if cached is not None:
            return self._outcome(task, cached, started, state=ExecutionState.COMPLETED)
        factory = self._factories.get(task.analyzer_id)
        if factory is None:
            return self._outcome(
                task,
                failure_result(task, reason="analyzer factory unavailable", kind="unsupported"),
                started,
                state=ExecutionState.FAILED,
                failure_kind="unsupported",
            )
        timeout = task.resource_limits.timeout_seconds
        if task.deadline_at is not None:
            timeout = min(timeout, max(0.001, (task.deadline_at - started).total_seconds()))
        facts_size = len(task.input.facts.to_json().encode())
        observation_count = sum(
            len(getattr(task.input.facts, group).observations)
            for group in ("git", "documentation", "issues", "cicd", "security", "code_health")
        )
        if facts_size > task.resource_limits.max_bytes or observation_count > task.resource_limits.max_files:
            return self._outcome(
                task,
                failure_result(task, reason="resource limit exceeded", kind="resource_limit"),
                started,
                state=ExecutionState.FAILED,
                failure_kind="resource_limit",
            )
        try:
            value = await asyncio.wait_for(self._invoke(factory, task.input), timeout=timeout)
            result = CategoryResult.model_validate(
                value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            )
            if (result.analysis_id, result.analyzer_id, result.category) != (
                task.analysis_id,
                task.analyzer_id,
                task.category,
            ):
                raise ValueError("factory returned a result for a different task")
            if result.status is not CategoryStatus.ERROR:
                self._cache[key] = result
            state = ExecutionState.FAILED if result.status is CategoryStatus.ERROR else ExecutionState.COMPLETED
            return self._outcome(
                task,
                result,
                started,
                state=state,
                failure_kind="analyzer_error" if state is ExecutionState.FAILED else None,
            )
        except TimeoutError:
            return self._outcome(
                task,
                failure_result(task, reason="analyzer execution timed out", kind="timeout"),
                started,
                state=ExecutionState.TIMEOUT,
                retryable=True,
                failure_kind="timeout",
            )
        except RetryableExecutionError:
            return self._outcome(
                task,
                failure_result(task, reason="transient analyzer failure", kind="error"),
                started,
                state=ExecutionState.FAILED,
                retryable=True,
                failure_kind="transient",
            )
        except asyncio.CancelledError:
            log.info(
                "analyzer_cancelled", analysis_id=task.analysis_id, task_id=task.task_id, analyzer_id=task.analyzer_id
            )
            raise
        except Exception as exc:
            log.warning(
                "analyzer_failed",
                analysis_id=task.analysis_id,
                task_id=task.task_id,
                analyzer_id=task.analyzer_id,
                error_type=type(exc).__name__,
            )
            return self._outcome(
                task,
                failure_result(task, reason="analyzer execution failed", kind="error"),
                started,
                state=ExecutionState.FAILED,
                failure_kind="error",
            )

    def _record(self, event: str, fields: dict[str, Any]) -> None:
        if self._telemetry is None:
            return
        try:
            self._telemetry.record(event, fields)
        except Exception as exc:  # telemetry must never escape task boundary
            log.warning("execution_telemetry_failed", event_name=event, error_type=type(exc).__name__)

    @staticmethod
    async def _invoke(factory: AnalyzerCallable, analyzer_input: Any) -> Any:
        if inspect.iscoroutinefunction(factory):
            return await factory(analyzer_input)
        value = await asyncio.to_thread(factory, analyzer_input)
        if inspect.isawaitable(value):
            return await value
        return value

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


__all__ = ["AnalyzerCallable", "LocalExecutor", "RetryableExecutionError", "failure_result"]
