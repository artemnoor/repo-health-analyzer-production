"""Local and worker-ready execution contracts for Repo Health analyzers."""

from .local import LocalExecutor, RetryableExecutionError
from .observability import ExecutionTelemetry, InMemoryTelemetry, redact_fields
from .tasks import AnalyzerTask, ExecutionOutcome, ExecutionState, ResourceLimits

__all__ = [
    "AnalyzerTask",
    "ExecutionOutcome",
    "ExecutionResultWriter",
    "ExecutionState",
    "ExecutionTelemetry",
    "InMemoryQueue",
    "InMemoryTelemetry",
    "LocalExecutor",
    "QueueConflictError",
    "QueueLease",
    "QueuePort",
    "ResourceLimits",
    "RetryableExecutionError",
    "SqlQueue",
    "WorkerExecutor",
    "redact_fields",
]


def __getattr__(name: str):
    """Keep contract-only task imports free of persistence side effects."""

    if name in {"InMemoryQueue", "QueueConflictError", "QueueLease", "QueuePort", "SqlQueue"}:
        from .queue import InMemoryQueue, QueueConflictError, QueueLease, QueuePort, SqlQueue

        return {
            "InMemoryQueue": InMemoryQueue,
            "QueueConflictError": QueueConflictError,
            "QueueLease": QueueLease,
            "QueuePort": QueuePort,
            "SqlQueue": SqlQueue,
        }[name]
    if name in {"ExecutionResultWriter", "WorkerExecutor"}:
        from .worker import ExecutionResultWriter, WorkerExecutor

        return {"ExecutionResultWriter": ExecutionResultWriter, "WorkerExecutor": WorkerExecutor}[name]
    raise AttributeError(name)
