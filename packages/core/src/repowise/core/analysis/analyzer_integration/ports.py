"""Small dependency-injection ports for the analyzer integration kernel."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Generic, Protocol, TypeVar

from .contracts import AnalyzerContext, AnalyzerResult
from .process import ProcessOutput, ProcessRequest

ScoreT_co = TypeVar("ScoreT_co", covariant=True)
ScoreT_contra = TypeVar("ScoreT_contra", contravariant=True)
AnalyzerFactory = Callable[[AnalyzerContext], AnalyzerResult | Mapping[str, Any]]


class CacheStore(Protocol):
    def get(self, key: str, **kwargs: Any) -> AnalyzerResult | None: ...

    def put(self, key: str, result: AnalyzerResult, **kwargs: Any) -> None: ...


class ProcessExecutor(Protocol):
    def run(self, request: ProcessRequest) -> ProcessOutput: ...


class ContextCollector(Protocol):
    def __call__(
        self, context: AnalyzerContext
    ) -> AnalyzerContext | Awaitable[AnalyzerContext]: ...


class ScoreComposer(Protocol, Generic[ScoreT_co]):
    def __call__(
        self, context: AnalyzerContext, results: tuple[AnalyzerResult, ...]
    ) -> ScoreT_co | None: ...


class PersistencePort(Protocol, Generic[ScoreT_contra]):
    def __call__(
        self,
        context: AnalyzerContext,
        results: tuple[AnalyzerResult, ...],
        score: ScoreT_contra | None,
    ) -> Any | Awaitable[Any]: ...


class PublicationPort(Protocol, Generic[ScoreT_contra]):
    def __call__(
        self, context: AnalyzerContext, score: ScoreT_contra | None
    ) -> Any | Awaitable[Any]: ...


class CheckpointPort(Protocol):
    async def begin(self, *, run_key: str, context: AnalyzerContext) -> Any: ...

    async def checkpoint(self, state: Any, *, phase: str, completed: tuple[str, ...]) -> None: ...

    async def complete(self, state: Any, *, phase: str, completed: tuple[str, ...]) -> None: ...

    async def fail(
        self, state: Any, *, phase: str, completed: tuple[str, ...], error: str
    ) -> None: ...

    async def resume(self, *, run_key: str, context: AnalyzerContext) -> Any | None: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...


# Descriptive aliases keep the port vocabulary ergonomic for integrations while
# retaining one implementation-free Protocol for each boundary.
AnalyzerCache = CacheStore
ProcessPort = ProcessExecutor
ContextPort = ContextCollector
CompositionPort = ScoreComposer
PersistenceHook = PersistencePort
PublicationHook = PublicationPort
CheckpointStore = CheckpointPort


__all__ = [
    "AnalyzerCache",
    "AnalyzerFactory",
    "CacheStore",
    "CheckpointPort",
    "CheckpointStore",
    "Clock",
    "CompositionPort",
    "ContextCollector",
    "ContextPort",
    "PersistenceHook",
    "PersistencePort",
    "ProcessExecutor",
    "ProcessPort",
    "PublicationHook",
    "PublicationPort",
    "ScoreComposer",
]
