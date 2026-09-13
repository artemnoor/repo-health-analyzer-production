import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    MetricValue,
)
from repowise.core.analysis.health.integrations.orchestrator import HealthOrchestrator
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry
from repowise.core.persistence._interfaces.job_store import JobRecord, JobState, JobStore


def _context(repo_id: str = "repo") -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id=repo_id,
        head_sha="head",
        as_of_ts=datetime(2026, 9, 11, tzinfo=UTC),
        capabilities=("local_scan",),
    )


def _registry(ids: list[str], factory):
    registry = AnalyzerRegistry()
    for analyzer_id in ids:
        registry.register(
            AnalyzerDefinition(
                id=analyzer_id,
                version="1",
                category="test",
                dimensions=("code",),
                cache_policy="none",
            ),
            factory(analyzer_id),
        )
    return registry


def _result(analyzer_id: str) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="1",
        status=AnalyzerStatus.PASS,
        score=80,
        metrics=(MetricValue(name=f"{analyzer_id}:score", dimension="code", score=80, denominator=1),),
        evidence=(),
        available_weight=1,
        total_weight=1,
    )


class MemoryJobStore(JobStore):
    def __init__(self) -> None:
        self.records: dict[str, JobRecord] = {}
        self.next_id = 1

    async def create_job(self, *, repository_id: str, phase: str, metadata: dict | None = None) -> JobRecord:
        now = datetime.now(UTC)
        record = JobRecord(
            id=str(self.next_id),
            repository_id=repository_id,
            phase=phase,
            state=JobState.PENDING,
            cursor=None,
            started_at=now,
            updated_at=now,
            error=None,
            metadata=metadata or {},
        )
        self.next_id += 1
        self.records[record.id] = record
        return record

    async def get_job(self, job_id: str) -> JobRecord | None:
        return self.records.get(job_id)

    async def update_state(self, job_id: str, state: JobState, *, cursor: str | None = None, error: str | None = None) -> JobRecord:
        record = self.records[job_id]
        updated = replace(
            record,
            state=state,
            cursor=cursor if cursor is not None else record.cursor,
            error=error if error is not None else record.error,
            updated_at=datetime.now(UTC),
        )
        self.records[job_id] = updated
        return updated

    async def checkpoint(self, job_id: str, cursor: str) -> JobRecord:
        return await self.update_state(job_id, self.records[job_id].state, cursor=cursor)

    async def find_resumable(self, *, repository_id: str | None = None) -> list[JobRecord]:
        return [
            record
            for record in self.records.values()
            if record.state in {JobState.PENDING, JobState.RUNNING}
            and (repository_id is None or record.repository_id == repository_id)
        ]

    async def list_jobs(self, *, repository_id: str | None = None, phase: str | None = None, state: JobState | None = None, limit: int = 100) -> list[JobRecord]:
        rows = [
            record
            for record in self.records.values()
            if (repository_id is None or record.repository_id == repository_id)
            and (phase is None or record.phase == phase)
            and (state is None or record.state == state)
        ]
        return rows[:limit]


@pytest.mark.asyncio
async def test_batch_bounds_concurrency_and_composes_results() -> None:
    active = 0
    peak = 0
    def factory(analyzer_id: str):
        def run(context: AnalyzerContext) -> AnalyzerResult:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.03)
            active -= 1
            return _result(analyzer_id)

        return run

    orchestrator = HealthOrchestrator(
        analyzer_registry=_registry(["a", "b", "c"], factory),
        max_concurrency=2,
        max_retries=0,
    )
    batch = await orchestrator.run_batch([_context("one"), _context("two")])

    assert batch.completed == 2
    assert batch.failed == 0
    assert peak <= 2
    assert all(outcome.score is not None and outcome.score.overall == 80 for outcome in batch.outcomes)


@pytest.mark.asyncio
async def test_failed_persist_is_checkpointed_and_resume_reuses_job() -> None:
    store = MemoryJobStore()
    calls = 0

    def factory(analyzer_id: str):
        return lambda context: _result(analyzer_id)

    async def persist(context, results, score):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated persistence interruption")

    orchestrator = HealthOrchestrator(analyzer_registry=_registry(["a"], factory), max_retries=0)
    first = await orchestrator.run_repository(_context(), job_store=store, persist=persist)
    assert first.status == "failed"
    job = next(iter(store.records.values()))
    cursor = json.loads(job.cursor or "{}")
    assert job.state is JobState.FAILED
    assert "compose" in cursor["completed"]

    second = await orchestrator.run_repository(_context(), job_store=store, persist=persist, resume=True)
    assert second.status == "completed"
    assert second.resumed is True
    assert second.job_id == first.job_id
    assert len(store.records) == 1


@pytest.mark.asyncio
async def test_dry_run_plans_without_calling_analyzer() -> None:
    called = False

    def factory(analyzer_id: str):
        def run(context: AnalyzerContext) -> AnalyzerResult:
            nonlocal called
            called = True
            return _result(analyzer_id)

        return run

    orchestrator = HealthOrchestrator(analyzer_registry=_registry(["a"], factory))
    outcome = await orchestrator.run_repository(_context(), dry_run=True)

    assert outcome.status == "skipped"
    assert outcome.dry_run is True
    assert outcome.planned_analyzers == ("a",)
    assert called is False
