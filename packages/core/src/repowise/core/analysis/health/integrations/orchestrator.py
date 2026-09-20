"""Health-edge compatibility facade over the neutral lifecycle."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any, TypeAlias

from ....analysis.analyzer_integration.lifecycle import (
    PHASES,
    BatchOutcome,
    LifecycleOrchestrator,
    RunOutcome,
    _resume_cursor,
)
from ....analysis.analyzer_integration.ports import (
    ContextCollector,
    PersistencePort,
    PublicationPort,
    ScoreComposer,
)
from ....persistence._interfaces.job_store import JobRecord, JobState, JobStore
from ..composite import CompositeHealthScore
from ..score_engine_v1 import compose_default_repo_health_score
from .contracts import AnalyzerContext
from .registry import AnalyzerRegistry
from .registry import registry as default_registry

PersistenceHook: TypeAlias = PersistencePort[CompositeHealthScore]
PublicationHook: TypeAlias = PublicationPort[CompositeHealthScore]

HEALTH_PIPELINE_PHASE = "health"
HEALTH_PHASES = PHASES


class HealthRunResult(RunOutcome[CompositeHealthScore]):
    """Concrete legacy result type with the historical public fields."""


class HealthBatchResult(BatchOutcome[CompositeHealthScore]):
    """Concrete legacy batch type with the historical public fields."""


def _cursor(completed: Iterable[str], *, phase: str) -> str:
    return json.dumps(
        {"phase": phase, "completed": sorted(set(completed))},
        sort_keys=True,
        separators=(",", ":"),
    )


class _JobStoreCheckpoint:
    """Adapt the health JobStore without exposing its types to the kernel."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.last_state: JobRecord | None = None

    async def begin(self, *, run_key: str, context: AnalyzerContext) -> JobRecord:
        job = await self.store.create_job(
            repository_id=context.repo_id,
            phase=HEALTH_PIPELINE_PHASE,
            metadata={
                "run_key": run_key,
                "repository_id": context.repo_id,
                "mode": context.mode,
            },
        )
        self.last_state = job
        self.last_state = await self.store.update_state(job.id, JobState.RUNNING)
        return self.last_state

    async def resume(self, *, run_key: str, context: AnalyzerContext) -> JobRecord | None:
        records = await self.store.find_resumable(repository_id=context.repo_id)
        records.extend(
            await self.store.list_jobs(
                repository_id=context.repo_id,
                phase=HEALTH_PIPELINE_PHASE,
                state=JobState.FAILED,
            )
        )
        matching = [
            record
            for record in records
            if record.phase == HEALTH_PIPELINE_PHASE
            and record.metadata.get("run_key") == run_key
            and _resume_cursor(record, run_key)[0]
        ]
        if not matching:
            return None
        job = max(matching, key=lambda record: record.updated_at)
        self.last_state = job
        self.last_state = await self.store.update_state(job.id, JobState.RUNNING)
        return self.last_state

    async def checkpoint(self, state: JobRecord, *, phase: str, completed: tuple[str, ...]) -> None:
        await self.store.checkpoint(state.id, _cursor(completed, phase=phase))

    async def complete(self, state: JobRecord, *, phase: str, completed: tuple[str, ...]) -> None:
        await self.store.update_state(
            state.id, JobState.COMPLETED, cursor=_cursor(completed, phase=phase)
        )

    async def fail(
        self, state: JobRecord, *, phase: str, completed: tuple[str, ...], error: str
    ) -> None:
        await self.store.update_state(
            state.id, JobState.FAILED, cursor=_cursor(completed, phase=phase), error=error
        )


class HealthOrchestrator(LifecycleOrchestrator[CompositeHealthScore]):
    """Preserve health APIs while injecting health scoring and JobStore ports."""

    def __init__(
        self,
        *,
        analyzer_registry: AnalyzerRegistry | None = None,
        max_concurrency: int = 2,
        max_retries: int = 1,
        composer: ScoreComposer[CompositeHealthScore] | None = None,
    ) -> None:
        super().__init__(
            analyzer_registry=analyzer_registry or default_registry,
            composer=composer
            or (
                lambda context, results: compose_default_repo_health_score(
                    results, repository_id=context.repo_id
                )
            ),
            max_concurrency=max_concurrency,
            max_retries=max_retries,
        )
        # Keep the historical public tuning attribute available to callers
        # while the neutral base tracks separate repository/analyzer limits.
        self.max_concurrency = max_concurrency

    async def run_repository(
        self,
        context: AnalyzerContext,
        *,
        collector: ContextCollector | None = None,
        composer: ScoreComposer[CompositeHealthScore] | None = None,
        persist: PersistenceHook | None = None,
        publish: PublicationHook | None = None,
        job_store: JobStore | None = None,
        selected_analyzers: Sequence[str] | None = None,
        resume: bool = False,
        dry_run: bool = False,
        _analyzer_semaphore: Any | None = None,
        _checkpoint_port: Any | None = None,
    ) -> HealthRunResult:
        outcome = await super().run_repository(
            context,
            collector=collector,
            composer=composer,
            persist=persist,
            publish=publish,
            selected_analyzers=selected_analyzers,
            resume=resume,
            dry_run=dry_run,
            _analyzer_semaphore=_analyzer_semaphore,
            _checkpoint_port=(
                _checkpoint_port
                or (_JobStoreCheckpoint(job_store) if job_store is not None else None)
            ),
        )
        return HealthRunResult(**outcome.__dict__)

    async def run_batch(
        self, contexts: Iterable[AnalyzerContext], **kwargs: Any
    ) -> HealthBatchResult:
        batch = await super().run_batch(contexts, **kwargs)
        return HealthBatchResult(**batch.__dict__)


__all__ = [
    "HEALTH_PHASES",
    "ContextCollector",
    "HealthBatchResult",
    "HealthOrchestrator",
    "HealthRunResult",
    "PersistenceHook",
    "PublicationHook",
]
