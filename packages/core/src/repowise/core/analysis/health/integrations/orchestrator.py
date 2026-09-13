"""Bounded, resumable orchestration for repository-health analysis.

The adapters remain owners of collection/parsing.  This module owns the
execution contract around them: capability planning, failure isolation,
bounded concurrency, phase checkpoints, composition, and publication hooks.
Keeping those concerns here lets the CLI, server scheduler, and batch workers
use exactly the same runtime without importing either application's wiring.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from ....persistence._interfaces.job_store import JobRecord, JobState, JobStore
from ..composite import CompositeHealthScore, compose_health_score
from .contracts import AnalyzerContext, AnalyzerResult, AnalyzerStatus
from .registry import AnalyzerRegistry, PlannedAnalyzer
from .registry import registry as default_registry

log = structlog.get_logger("health.orchestrator")

HEALTH_PIPELINE_PHASE = "health"
HEALTH_PHASES: tuple[str, ...] = (
    "plan",
    "collect",
    "analyze",
    "compose",
    "persist",
    "publish",
)

ContextCollector = Callable[[AnalyzerContext], AnalyzerContext | Awaitable[AnalyzerContext]]
PersistenceHook = Callable[
    [AnalyzerContext, tuple[AnalyzerResult, ...], CompositeHealthScore], Any | Awaitable[Any]
]
PublicationHook = Callable[
    [AnalyzerContext, CompositeHealthScore], Any | Awaitable[Any]
]


@dataclass(frozen=True)
class HealthRunResult:
    """Redacted outcome of one repository run."""

    repository_id: str
    status: str
    phase: str
    planned_analyzers: tuple[str, ...] = ()
    results: tuple[AnalyzerResult, ...] = ()
    score: CompositeHealthScore | None = None
    resumed: bool = False
    dry_run: bool = False
    job_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class HealthBatchResult:
    """Stable batch summary; individual repository failures are isolated."""

    outcomes: tuple[HealthRunResult, ...]
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


def _run_key(context: AnalyzerContext, selected: Sequence[str] | None) -> str:
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


def _cursor(completed: Iterable[str], *, phase: str) -> str:
    return json.dumps(
        {"phase": phase, "completed": sorted(set(completed))},
        sort_keys=True,
        separators=(",", ":"),
    )


def _completed_from_cursor(record: JobRecord | None, run_key: str) -> set[str]:
    if record is None or record.metadata.get("run_key") != run_key or not record.cursor:
        return set()
    try:
        payload = json.loads(record.cursor)
    except (TypeError, ValueError):
        return set()
    completed = payload.get("completed", []) if isinstance(payload, Mapping) else []
    if not isinstance(completed, list):
        return set()
    return {str(item) for item in completed if str(item) in HEALTH_PHASES}


async def _maybe_await(value: Any) -> Any:
    return await value if asyncio.iscoroutine(value) or isinstance(value, Awaitable) else value


class HealthOrchestrator:
    """Execute health analyzers with bounded resources and durable cursors."""

    def __init__(
        self,
        *,
        analyzer_registry: AnalyzerRegistry | None = None,
        max_concurrency: int = 2,
        max_retries: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.registry = analyzer_registry or default_registry
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries

    async def _find_job(
        self,
        job_store: JobStore,
        context: AnalyzerContext,
        run_key: str,
        *,
        resume: bool,
    ) -> JobRecord | None:
        if not resume:
            return None
        records = await job_store.find_resumable(repository_id=context.repo_id)
        # A failed phase is also resumable when the caller explicitly asks for
        # it.  ``find_resumable`` intentionally remains conservative for
        # generic pipeline consumers, so consult the read-side API here.
        records.extend(
            await job_store.list_jobs(
                repository_id=context.repo_id,
                phase=HEALTH_PIPELINE_PHASE,
                state=JobState.FAILED,
            )
        )
        matching = [
            record
            for record in records
            if record.phase == HEALTH_PIPELINE_PHASE and record.metadata.get("run_key") == run_key
        ]
        return max(matching, key=lambda record: record.updated_at) if matching else None

    async def _checkpoint(
        self,
        job_store: JobStore | None,
        job_id: str | None,
        completed: set[str],
        phase: str,
    ) -> None:
        if job_store is None or job_id is None:
            return
        completed.add(phase)
        await job_store.checkpoint(job_id, _cursor(completed, phase=phase))
        log.debug("phase_checkpoint", phase=phase, job_id=job_id, completed=sorted(completed))

    async def _run_analyzer(
        self,
        planned: PlannedAnalyzer,
        context: AnalyzerContext,
    ) -> AnalyzerResult:
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            result = await asyncio.to_thread(self.registry.run, planned, context)
            if result.status not in {AnalyzerStatus.ERROR} or attempt == attempts:
                return result
            log.warning(
                "analyzer_retry",
                repo_id=context.repo_id,
                analyzer_id=planned.definition.id,
                attempt=attempt,
                max_retries=self.max_retries,
            )
        raise AssertionError("analyzer retry loop did not return")

    async def run_repository(
        self,
        context: AnalyzerContext,
        *,
        collector: ContextCollector | None = None,
        persist: PersistenceHook | None = None,
        publish: PublicationHook | None = None,
        job_store: JobStore | None = None,
        selected_analyzers: Sequence[str] | None = None,
        resume: bool = False,
        dry_run: bool = False,
        _analyzer_semaphore: asyncio.Semaphore | None = None,
    ) -> HealthRunResult:
        """Run one repository; every analyzer failure becomes a visible result."""
        run_key = _run_key(context, selected_analyzers)
        job: JobRecord | None = None
        completed: set[str] = set()
        planned: tuple[PlannedAnalyzer, ...] = ()
        results: tuple[AnalyzerResult, ...] = ()
        composite: CompositeHealthScore | None = None
        phase = "plan"
        started = time.perf_counter()

        try:
            if job_store is not None:
                job = await self._find_job(job_store, context, run_key, resume=resume)
                if job is None:
                    job = await job_store.create_job(
                        repository_id=context.repo_id,
                        phase=HEALTH_PIPELINE_PHASE,
                        metadata={"run_key": run_key, "mode": context.mode},
                    )
                await job_store.update_state(job.id, JobState.RUNNING)
                completed = _completed_from_cursor(job, run_key)

            phase = "plan"
            planned = self.registry.plan(context)
            if selected_analyzers is not None:
                selected = {item.strip() for item in selected_analyzers if item.strip()}
                known = {item.definition.id for item in planned}
                unknown = selected - known
                if unknown:
                    raise ValueError(f"unknown analyzer IDs: {', '.join(sorted(unknown))}")
                planned = tuple(item for item in planned if item.definition.id in selected)
            if not planned:
                raise ValueError("no analyzers selected")
            await self._checkpoint(job_store, job.id if job else None, completed, "plan")
            log.info(
                "health_plan_ready",
                repo_id=context.repo_id,
                analyzer_count=len(planned),
                skipped=sum(not item.ready for item in planned),
            )

            phase = "collect"
            collected_context = await _maybe_await(collector(context) if collector else context)
            if not isinstance(collected_context, AnalyzerContext):
                collected_context = AnalyzerContext.model_validate(collected_context)
            context = collected_context
            await self._checkpoint(job_store, job.id if job else None, completed, "collect")

            if dry_run:
                log.info("health_dry_run", repo_id=context.repo_id, analyzer_count=len(planned))
                if job_store is not None and job is not None:
                    await job_store.update_state(job.id, JobState.COMPLETED, cursor=_cursor(completed, phase="dry-run"))
                return HealthRunResult(
                    repository_id=context.repo_id,
                    status="skipped",
                    phase="collect",
                    planned_analyzers=tuple(item.definition.id for item in planned),
                    resumed=bool(completed),
                    dry_run=True,
                    job_id=job.id if job else None,
                )

            phase = "analyze"
            semaphore = _analyzer_semaphore or asyncio.Semaphore(self.max_concurrency)

            async def run_bounded(item: PlannedAnalyzer) -> AnalyzerResult:
                async with semaphore:
                    return await self._run_analyzer(item, context)

            results = tuple(await asyncio.gather(*(run_bounded(item) for item in planned)))
            await self._checkpoint(job_store, job.id if job else None, completed, "analyze")
            log.info(
                "health_analysis_complete",
                repo_id=context.repo_id,
                result_count=len(results),
                failed=sum(result.status == AnalyzerStatus.ERROR for result in results),
            )

            phase = "compose"
            composite = compose_health_score(results, repository_id=context.repo_id)
            await self._checkpoint(job_store, job.id if job else None, completed, "compose")
            log.info(
                "health_composition_complete",
                repo_id=context.repo_id,
                overall=composite.overall,
                coverage=composite.coverage,
            )

            phase = "persist"
            if persist is not None:
                await _maybe_await(persist(context, results, composite))
            await self._checkpoint(job_store, job.id if job else None, completed, "persist")

            phase = "publish"
            if publish is not None:
                await _maybe_await(publish(context, composite))
            await self._checkpoint(job_store, job.id if job else None, completed, "publish")
            if job_store is not None and job is not None:
                await job_store.update_state(job.id, JobState.COMPLETED, cursor=_cursor(completed, phase=phase))
            log.info(
                "health_repository_complete",
                repo_id=context.repo_id,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return HealthRunResult(
                repository_id=context.repo_id,
                status="completed",
                phase=phase,
                planned_analyzers=tuple(item.definition.id for item in planned),
                results=results,
                score=composite,
                resumed=bool(completed),
                job_id=job.id if job else None,
            )
        except Exception as exc:
            if job_store is not None and job is not None:
                await job_store.update_state(
                    job.id,
                    JobState.FAILED,
                    cursor=_cursor(completed, phase=phase),
                    error=type(exc).__name__,
                )
            log.error(
                "health_repository_failed",
                repo_id=context.repo_id,
                phase=phase,
                error_type=type(exc).__name__,
            )
            return HealthRunResult(
                repository_id=context.repo_id,
                status="failed",
                phase=phase,
                planned_analyzers=tuple(item.definition.id for item in planned),
                results=results,
                score=composite,
                resumed=bool(completed),
                job_id=job.id if job else None,
                error=type(exc).__name__,
            )

    async def run_batch(
        self,
        contexts: Iterable[AnalyzerContext],
        **kwargs: Any,
    ) -> HealthBatchResult:
        """Run repositories concurrently while isolating one repository's failure."""
        started_at = time.perf_counter()
        repository_semaphore = asyncio.Semaphore(self.max_concurrency)
        analyzer_semaphore = asyncio.Semaphore(self.max_concurrency)
        context_list = tuple(contexts)
        log.info("health_batch_started", repository_count=len(context_list), max_concurrency=self.max_concurrency)

        async def run_bounded(context: AnalyzerContext) -> HealthRunResult:
            async with repository_semaphore:
                return await self.run_repository(
                    context,
                    _analyzer_semaphore=analyzer_semaphore,
                    **kwargs,
                )

        outcomes = tuple(await asyncio.gather(*(run_bounded(context) for context in context_list)))
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        summary = HealthBatchResult(
            outcomes=outcomes,
            started_at=started_at,
            duration_ms=duration_ms,
            max_concurrency=self.max_concurrency,
        )
        log.info(
            "health_batch_complete",
            repository_count=len(outcomes),
            completed=summary.completed,
            failed=summary.failed,
            skipped=summary.skipped,
            duration_ms=duration_ms,
        )
        return summary


__all__ = [
    "HEALTH_PHASES",
    "HealthBatchResult",
    "HealthOrchestrator",
    "HealthRunResult",
]
