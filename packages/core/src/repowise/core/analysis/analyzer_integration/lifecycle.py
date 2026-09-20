"""Product-neutral analyzer lifecycle and bounded orchestration."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

import structlog

from .contracts import AnalyzerContext, AnalyzerResult, AnalyzerStatus
from .ports import ContextCollector, PersistencePort, PublicationPort, ScoreComposer
from .registry import AnalyzerRegistry, PlannedAnalyzer
from .registry import registry as default_registry
from .runner import AnalyzerRunner

log = structlog.get_logger(__name__)
ScoreT = TypeVar("ScoreT")

PHASES: tuple[str, ...] = ("plan", "collect", "analyze", "compose", "persist", "publish")
PhaseHook = Callable[[str, Any], Any | Awaitable[Any]]


def _resume_cursor(state: object, run_key_value: str) -> tuple[bool, tuple[str, ...]]:
    """Return whether an opaque checkpoint is safe to reuse and its phases.

    A checkpoint is not resumable merely because a provider returned an object.
    The metadata and cursor must both belong to this run, and the cursor must
    contain at least one known completed phase.  This prevents a foreign or
    half-created job from receiving later transitions.
    """

    def state_value(name: str) -> object:
        if isinstance(state, Mapping):
            return state.get(name)
        return getattr(state, name, None)

    metadata = state_value("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("run_key") != run_key_value:
        return False, ()
    cursor = state_value("cursor")
    if not cursor:
        return False, ()
    try:
        payload = json.loads(cast(str | bytes | bytearray, cursor))
    except (TypeError, ValueError):
        return False, ()
    if not isinstance(payload, Mapping):
        return False, ()
    phase = payload.get("phase")
    if phase not in (*PHASES, "dry-run"):
        return False, ()
    completed = payload.get("completed", []) if isinstance(payload, Mapping) else []
    if not isinstance(completed, list):
        return False, ()
    normalized = tuple(sorted({str(item) for item in completed if str(item) in PHASES}))
    if len(normalized) != len(completed) or not normalized:
        return False, ()
    return True, normalized


def _completed_from_state(state: object, run_key_value: str) -> tuple[str, ...]:
    """Read only durable, run-matching phase markers from an opaque state."""
    usable, completed = _resume_cursor(state, run_key_value)
    return completed if usable else ()


def _safe_exception_message(exc: BaseException) -> str:
    """Keep failure logs diagnostic without exposing exception payloads."""
    return f"{type(exc).__name__} (message redacted)"


def _state_matches_run(state: object, run_key_value: str, repository_id: str) -> bool:
    """Accept checkpoint state only when its identity is explicit and current."""
    if isinstance(state, Mapping):
        metadata = state.get("metadata")
    else:
        metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, Mapping) or metadata.get("run_key") != run_key_value:
        return False
    stored_repository_id = metadata.get("repository_id")
    return stored_repository_id in (None, repository_id)


@dataclass(frozen=True)
class RunOutcome(Generic[ScoreT]):
    repository_id: str
    status: str
    phase: str
    planned_analyzers: tuple[str, ...] = ()
    results: tuple[AnalyzerResult, ...] = ()
    score: ScoreT | None = None
    resumed: bool = False
    dry_run: bool = False
    job_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchOutcome(Generic[ScoreT]):
    outcomes: tuple[RunOutcome[ScoreT], ...]
    started_at: float
    duration_ms: int
    max_concurrency: int

    @property
    def completed(self) -> int:
        return sum(outcome.status == "completed" for outcome in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def skipped(self) -> int:
        return sum(outcome.status == "skipped" for outcome in self.outcomes)


def run_key(context: AnalyzerContext, selected: Sequence[str] | None) -> str:
    payload = {
        "repo_id": context.repo_id,
        "head_sha": context.head_sha,
        "as_of_ts": context.as_of_ts.isoformat(),
        "scope": context.scope,
        "mode": context.mode,
        "config_digest": context.config_digest,
        "analyzers": sorted(selected or ()),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class LifecycleOrchestrator(Generic[ScoreT]):
    """Run the six generic phases while keeping product score opaque."""

    def __init__(
        self,
        *,
        analyzer_registry: AnalyzerRegistry | None = None,
        runner: AnalyzerRunner | None = None,
        collector: ContextCollector | None = None,
        composer: ScoreComposer[ScoreT] | None = None,
        persist: PersistencePort[ScoreT] | None = None,
        publish: PublicationPort[ScoreT] | None = None,
        checkpoint: Any | None = None,
        hooks: Mapping[str, PhaseHook] | None = None,
        max_analyzer_concurrency: int = 2,
        max_repository_concurrency: int = 2,
        max_concurrency: int | None = None,
        max_retries: int = 1,
        backoff: Callable[[int], Any] | None = None,
    ) -> None:
        if max_concurrency is not None:
            max_analyzer_concurrency = max_repository_concurrency = max_concurrency
        if max_analyzer_concurrency < 1 or max_repository_concurrency < 1:
            raise ValueError("concurrency limits must be at least 1")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.registry = analyzer_registry or default_registry
        self.runner = runner or AnalyzerRunner()
        self.collector = collector
        self.composer = composer
        self.persist = persist
        self.publish = publish
        self.checkpoint = checkpoint
        self.hooks = dict(hooks or {})
        self.max_analyzer_concurrency = max_analyzer_concurrency
        self.max_repository_concurrency = max_repository_concurrency
        self.max_retries = max_retries
        self.backoff = backoff

    async def _hook(self, phase: str, value: Any) -> None:
        hook = self.hooks.get(phase)
        if hook is not None:
            await _maybe_await(hook(phase, value))

    async def _checkpoint_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self.checkpoint is None or not hasattr(self.checkpoint, method):
            return None
        return await _maybe_await(getattr(self.checkpoint, method)(*args, **kwargs))

    async def _retry_analyzer(
        self,
        planned: PlannedAnalyzer,
        context: AnalyzerContext,
        semaphore: asyncio.Semaphore,
        *,
        correlation_key: str,
        completed_phases: tuple[str, ...],
    ) -> AnalyzerResult:
        for attempt in range(1, self.max_retries + 2):
            async with semaphore:
                result = await asyncio.to_thread(
                    self.runner.run,
                    planned,
                    context,
                    correlation_key=correlation_key,
                    completed_phases=completed_phases,
                )
            if result.status is not AnalyzerStatus.ERROR or attempt > self.max_retries:
                return result
            log.warning(
                "analyzer_retry",
                analyzer_id=planned.definition.id,
                analyzer_version=planned.definition.version,
                run_key=correlation_key,
                repository_id=context.repo_id,
                phase="analyze",
                completed_phases=completed_phases,
                status="retrying",
                duration_ms=result.duration_ms,
                cache_hit=result.cache_hit,
                timeout=any(item.kind == "timeout" for item in result.limitations),
                failure_kind=(
                    str(result.diagnostics.get("error_type"))
                    if result.diagnostics.get("error_type")
                    else result.limitations[0].kind
                    if result.limitations
                    else "error"
                ),
                attempt=attempt,
                max_retries=self.max_retries,
            )
            if self.backoff is not None:
                await _maybe_await(self.backoff(attempt))
        raise AssertionError("analyzer retry loop did not return")

    async def run_repository(
        self,
        context: AnalyzerContext,
        *,
        collector: ContextCollector | None = None,
        composer: ScoreComposer[ScoreT] | None = None,
        persist: PersistencePort[ScoreT] | None = None,
        publish: PublicationPort[ScoreT] | None = None,
        selected_analyzers: Sequence[str] | None = None,
        resume: bool = False,
        dry_run: bool = False,
        _analyzer_semaphore: asyncio.Semaphore | None = None,
        _checkpoint_port: Any | None = None,
    ) -> RunOutcome[ScoreT]:
        key = run_key(context, selected_analyzers)
        completed: list[str] = []
        state = None
        planned: tuple[PlannedAnalyzer, ...] = ()
        results: tuple[AnalyzerResult, ...] = ()
        score: ScoreT | None = None
        phase = "plan"
        started = time.perf_counter()
        job_id: str | None = None
        resumed = False
        checkpoint_port = _checkpoint_port or self.checkpoint
        phase_started_at: float | None = None

        def mark_completed(name: str) -> None:
            if name not in completed:
                completed.append(name)

        def phase_started(name: str) -> None:
            nonlocal phase, phase_started_at
            phase = name
            phase_started_at = time.perf_counter()
            log.info(
                "phase_started",
                run_key=key,
                repository_id=context.repo_id,
                phase=name,
                completed_phases=tuple(completed),
                status="running",
                duration_ms=0,
                resumed=resumed,
                dry_run=dry_run,
                job_id=job_id,
            )

        def phase_finished(name: str, *, status: str, failure_kind: str | None = None) -> None:
            nonlocal phase_started_at
            duration_ms = (
                max(0, int((time.perf_counter() - phase_started_at) * 1000))
                if phase_started_at is not None
                else 0
            )
            log.info(
                "phase_finished",
                run_key=key,
                repository_id=context.repo_id,
                phase=name,
                completed_phases=tuple(completed),
                status=status,
                duration_ms=duration_ms,
                failure_kind=failure_kind,
                resumed=resumed,
                dry_run=dry_run,
                job_id=job_id,
            )
            phase_started_at = None

        async def checkpoint_call(method: str, *args: Any, **kwargs: Any) -> Any:
            nonlocal job_id, state
            if checkpoint_port is None or not hasattr(checkpoint_port, method):
                return None
            if method in {"checkpoint", "complete", "fail"} and args and args[0] is None:
                log.warning(
                    "checkpoint_skipped",
                    run_key=key,
                    repository_id=context.repo_id,
                    phase=str(kwargs.get("phase", phase)),
                    completed_phases=tuple(kwargs.get("completed", tuple(completed))),
                    status="skipped",
                    duration_ms=0,
                    failure_kind="missing_state",
                    operation=method,
                    resumed=resumed,
                    dry_run=dry_run,
                    job_id=job_id,
                )
                return None
            checkpoint_started = time.perf_counter()
            checkpoint_phase = str(kwargs.get("phase", phase))
            completed_phases = tuple(kwargs.get("completed", tuple(completed)))
            try:
                result = await _maybe_await(getattr(checkpoint_port, method)(*args, **kwargs))
            except Exception as exc:
                if state is None and method in {"begin", "resume"}:
                    # Some stores create a durable job before a later begin
                    # transition fails and expose it as ``last_state``.  Keep
                    # that state available for isolated failure handling, but
                    # never adopt a provider's foreign run as a fallback.
                    candidate_state = getattr(checkpoint_port, "last_state", None) or getattr(
                        checkpoint_port, "state", None
                    )
                    if _state_matches_run(candidate_state, key, context.repo_id):
                        state = candidate_state
                        if state is not None:
                            job_id = getattr(state, "job_id", None) or getattr(state, "id", None)
                duration_ms = max(0, int((time.perf_counter() - checkpoint_started) * 1000))
                log.error(
                    "checkpoint_failed",
                    run_key=key,
                    repository_id=context.repo_id,
                    phase=checkpoint_phase,
                    completed_phases=completed_phases,
                    status="failed",
                    duration_ms=duration_ms,
                    failure_kind=type(exc).__name__,
                    operation=method,
                    resumed=resumed,
                    dry_run=dry_run,
                    job_id=job_id,
                )
                log.debug(
                    "checkpoint_failure_detail",
                    run_key=key,
                    repository_id=context.repo_id,
                    phase=checkpoint_phase,
                    error_type=type(exc).__name__,
                    error_message=_safe_exception_message(exc),
                    status="failed",
                    duration_ms=duration_ms,
                    failure_kind=type(exc).__name__,
                    operation=method,
                    resumed=resumed,
                    dry_run=dry_run,
                    job_id=job_id,
                )
                raise
            log.debug(
                "checkpoint",
                run_key=key,
                repository_id=context.repo_id,
                phase=checkpoint_phase,
                completed_phases=completed_phases,
                status=("matched" if method == "resume" and result is not None else "not_found")
                if method == "resume"
                else "completed",
                duration_ms=max(0, int((time.perf_counter() - checkpoint_started) * 1000)),
                failure_kind="not_found" if method == "resume" and result is None else None,
                operation=method,
                resumed=resumed,
                dry_run=dry_run,
                job_id=job_id,
            )
            return result

        log.info(
            "lifecycle_started",
            run_key=key,
            repository_id=context.repo_id,
            phase="plan",
            completed_phases=(),
            status="running",
            duration_ms=0,
            resume_requested=resume,
            resumed=resumed,
            dry_run=dry_run,
            job_id=job_id,
            failure_kind=None,
        )

        try:
            phase_started("plan")
            if resume:
                candidate = await checkpoint_call("resume", run_key=key, context=context)
                usable, resumed_phases = (
                    _resume_cursor(candidate, key) if candidate is not None else (False, ())
                )
                if usable:
                    state = candidate
                    completed.extend(resumed_phases)
                    resumed = bool(resumed_phases)
                else:
                    # A resume candidate is read-only until its run key and
                    # cursor have been validated. Never retain a stale,
                    # malformed, or foreign state for later transitions.
                    state = None
                    resumed = False
                    candidate = None
                    log.warning(
                        "checkpoint_discarded",
                        run_key=key,
                        repository_id=context.repo_id,
                        phase="plan",
                        completed_phases=(),
                        status="discarded",
                        duration_ms=0,
                        failure_kind="missing_or_invalid",
                        operation="resume",
                        checkpoint_match=False,
                        dry_run=dry_run,
                        job_id=None,
                    )
                log.debug(
                    "checkpoint_resolution",
                    run_key=key,
                    repository_id=context.repo_id,
                    phase="plan",
                    completed_phases=tuple(completed),
                    status="matched" if usable else "discarded",
                    duration_ms=0,
                    failure_kind=None if usable else "missing_or_invalid",
                    checkpoint_match=usable,
                    dry_run=dry_run,
                    job_id=job_id,
                )
                if usable and state is not None:
                    job_id = getattr(state, "job_id", None) or getattr(state, "id", None)
            if state is None:
                state = await checkpoint_call("begin", run_key=key, context=context)
                if state is not None:
                    job_id = getattr(state, "job_id", None) or getattr(state, "id", None)

            planned = self.registry.plan(context, run_key_value=key)
            if selected_analyzers is not None:
                selected = {item.strip() for item in selected_analyzers if item.strip()}
                known = {item.definition.id for item in planned}
                unknown = selected - known
                if unknown:
                    raise ValueError(f"unknown analyzer IDs: {', '.join(sorted(unknown))}")
                planned = tuple(item for item in planned if item.definition.id in selected)
            if not planned:
                raise ValueError("no analyzers selected")
            mark_completed("plan")
            await checkpoint_call("checkpoint", state, phase="plan", completed=tuple(completed))
            await self._hook("plan", tuple(item.definition.id for item in planned))
            phase_finished("plan", status="completed")

            phase_started("collect")
            active_collector = collector or self.collector
            if active_collector is not None:
                collected = await _maybe_await(active_collector(context))
                context = (
                    collected
                    if isinstance(collected, AnalyzerContext)
                    else AnalyzerContext.model_validate(collected)
                )
            mark_completed("collect")
            await checkpoint_call("checkpoint", state, phase="collect", completed=tuple(completed))
            await self._hook("collect", context)
            phase_finished("collect", status="completed")

            if dry_run:
                await checkpoint_call(
                    "complete", state, phase="dry-run", completed=tuple(completed)
                )
                log.info(
                    "lifecycle_finished",
                    run_key=key,
                    repository_id=context.repo_id,
                    phase="collect",
                    completed_phases=tuple(completed),
                    status="skipped",
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    failure_kind=None,
                    dry_run=True,
                    resumed=resumed,
                    job_id=job_id,
                )
                return RunOutcome(
                    repository_id=context.repo_id,
                    status="skipped",
                    phase="collect",
                    planned_analyzers=tuple(item.definition.id for item in planned),
                    resumed=resumed,
                    dry_run=True,
                    job_id=job_id,
                )

            phase_started("analyze")
            semaphore = _analyzer_semaphore or asyncio.Semaphore(self.max_analyzer_concurrency)
            results = tuple(
                await asyncio.gather(
                    *(
                        self._retry_analyzer(
                            item,
                            context,
                            semaphore,
                            correlation_key=key,
                            completed_phases=tuple(completed),
                        )
                        for item in planned
                    )
                )
            )
            mark_completed("analyze")
            await checkpoint_call("checkpoint", state, phase="analyze", completed=tuple(completed))
            await self._hook("analyze", results)
            phase_finished("analyze", status="completed")

            phase_started("compose")
            active_composer = composer or self.composer
            if active_composer is not None:
                score = await _maybe_await(active_composer(context, results))
            mark_completed("compose")
            await checkpoint_call("checkpoint", state, phase="compose", completed=tuple(completed))
            await self._hook("compose", score)
            phase_finished("compose", status="completed")

            phase_started("persist")
            active_persist = persist or self.persist
            if active_persist is not None:
                await _maybe_await(active_persist(context, results, score))
            mark_completed("persist")
            await checkpoint_call("checkpoint", state, phase="persist", completed=tuple(completed))
            await self._hook("persist", score)
            phase_finished("persist", status="completed")

            phase_started("publish")
            active_publish = publish or self.publish
            if active_publish is not None:
                await _maybe_await(active_publish(context, score))
            mark_completed("publish")
            await checkpoint_call("checkpoint", state, phase="publish", completed=tuple(completed))
            await self._hook("publish", score)
            phase_finished("publish", status="completed")
            await checkpoint_call("complete", state, phase=phase, completed=tuple(completed))
            log.info(
                "repository_complete",
                run_key=key,
                repository_id=context.repo_id,
                phase=phase,
                completed_phases=tuple(completed),
                status="completed",
                duration_ms=int((time.perf_counter() - started) * 1000),
                failure_kind=None,
                resumed=resumed,
                dry_run=False,
                job_id=job_id,
            )
            log.info(
                "lifecycle_finished",
                run_key=key,
                repository_id=context.repo_id,
                phase=phase,
                completed_phases=tuple(completed),
                status="completed",
                duration_ms=int((time.perf_counter() - started) * 1000),
                failure_kind=None,
                dry_run=False,
                result_count=len(results),
                resumed=resumed,
                job_id=job_id,
            )
            return RunOutcome(
                repository_id=context.repo_id,
                status="completed",
                phase=phase,
                planned_analyzers=tuple(item.definition.id for item in planned),
                results=results,
                score=score,
                resumed=resumed,
                job_id=job_id,
            )
        except Exception as exc:
            if phase_started_at is not None:
                phase_finished(phase, status="failed", failure_kind=type(exc).__name__)
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            log.error(
                "repository_failed",
                run_key=key,
                repository_id=context.repo_id,
                phase=phase,
                completed_phases=tuple(completed),
                status="failed",
                duration_ms=duration_ms,
                failure_kind=type(exc).__name__,
                resumed=resumed,
                dry_run=dry_run,
                job_id=job_id,
            )
            log.error(
                "lifecycle_failed",
                run_key=key,
                repository_id=context.repo_id,
                phase=phase,
                completed_phases=tuple(completed),
                status="failed",
                duration_ms=duration_ms,
                failure_kind=type(exc).__name__,
                resumed=resumed,
                dry_run=dry_run,
                job_id=job_id,
            )
            log.debug(
                "lifecycle_failure_detail",
                run_key=key,
                repository_id=context.repo_id,
                phase=phase,
                error_type=type(exc).__name__,
                error_message=_safe_exception_message(exc),
                status="failed",
                duration_ms=duration_ms,
                failure_kind=type(exc).__name__,
                resumed=resumed,
                dry_run=dry_run,
                job_id=job_id,
            )
            if state is not None:
                try:
                    await checkpoint_call(
                        "fail",
                        state,
                        phase=phase,
                        completed=tuple(completed),
                        error=type(exc).__name__,
                    )
                except Exception as checkpoint_exc:
                    log.error(
                        "checkpoint_fail_failed",
                        run_key=key,
                        repository_id=context.repo_id,
                        phase=phase,
                        completed_phases=tuple(completed),
                        status="failed",
                        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                        failure_kind=type(checkpoint_exc).__name__,
                        operation="fail",
                        resumed=resumed,
                        dry_run=dry_run,
                        job_id=job_id,
                    )
            return RunOutcome(
                repository_id=context.repo_id,
                status="failed",
                phase=phase,
                planned_analyzers=tuple(item.definition.id for item in planned),
                results=results,
                score=score,
                resumed=resumed,
                job_id=job_id,
                error=type(exc).__name__,
            )

    async def run_batch(
        self, contexts: Iterable[AnalyzerContext], **kwargs: Any
    ) -> BatchOutcome[ScoreT]:
        started = time.perf_counter()
        context_list = tuple(contexts)
        repository_semaphore = asyncio.Semaphore(self.max_repository_concurrency)
        analyzer_semaphore = asyncio.Semaphore(self.max_analyzer_concurrency)
        log.info(
            "batch_started",
            run_key=None,
            repository_id=None,
            phase="batch",
            completed_phases=(),
            repository_count=len(context_list),
            status="running",
            duration_ms=0,
            failure_kind=None,
            max_concurrency=self.max_repository_concurrency,
        )

        async def bounded(context: AnalyzerContext) -> RunOutcome[ScoreT]:
            async with repository_semaphore:
                return await self.run_repository(
                    context, _analyzer_semaphore=analyzer_semaphore, **kwargs
                )

        outcomes = tuple(await asyncio.gather(*(bounded(context) for context in context_list)))
        result = BatchOutcome(
            outcomes=outcomes,
            started_at=started,
            duration_ms=int((time.perf_counter() - started) * 1000),
            max_concurrency=self.max_repository_concurrency,
        )
        log.info(
            "batch_complete",
            run_key=None,
            repository_id=None,
            phase="batch",
            completed_phases=(),
            repository_count=len(outcomes),
            completed_count=result.completed,
            skipped_count=result.skipped,
            failed_count=result.failed,
            status="completed" if result.failed == 0 else "failed",
            duration_ms=result.duration_ms,
        )
        return result


AnalyzerOrchestrator = LifecycleOrchestrator
Orchestrator = LifecycleOrchestrator

__all__ = [
    "PHASES",
    "AnalyzerOrchestrator",
    "BatchOutcome",
    "LifecycleOrchestrator",
    "Orchestrator",
    "RunOutcome",
    "run_key",
]
