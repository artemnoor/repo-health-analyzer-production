"""Local and worker execution modes with one serialized task contract."""

from .local import AnalyzerCallable, LocalExecutor, RetryableExecutionError, failure_result
from .observability import ExecutionTelemetry, NullTelemetry
from .worker import WorkerExecutor

__all__ = [
    "AnalyzerCallable",
    "ExecutionTelemetry",
    "LocalExecutor",
    "NullTelemetry",
    "RetryableExecutionError",
    "WorkerExecutor",
    "failure_result",
]
