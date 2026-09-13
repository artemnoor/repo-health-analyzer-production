"""Health batch lifecycle against the real orchestrator contract."""

from __future__ import annotations

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


class _Store(JobStore):
    def __init__(self) -> None:
        self.rows: dict[str, JobRecord] = {}

    async def create_job(self, *, repository_id, phase, metadata=None):
        now = datetime.now(UTC)
        row = JobRecord("health-job", repository_id, phase, JobState.PENDING, None, now, now, None, metadata or {})
        self.rows[row.id] = row
        return row

    async def get_job(self, job_id):
        return self.rows.get(job_id)

    async def update_state(self, job_id, state, *, cursor=None, error=None):
        row = self.rows[job_id]
        row = replace(row, state=state, cursor=cursor or row.cursor, error=error or row.error, updated_at=datetime.now(UTC))
        self.rows[job_id] = row
        return row

    async def checkpoint(self, job_id, cursor):
        return await self.update_state(job_id, self.rows[job_id].state, cursor=cursor)

    async def find_resumable(self, *, repository_id=None):
        return [
            row for row in self.rows.values()
            if row.state in {JobState.PENDING, JobState.RUNNING}
            and (repository_id is None or row.repository_id == repository_id)
        ]

    async def list_jobs(self, *, repository_id=None, phase=None, state=None, limit=100):
        return [
            row for row in self.rows.values()
            if (repository_id is None or row.repository_id == repository_id)
            and (phase is None or row.phase == phase)
            and (state is None or row.state == state)
        ][:limit]


def _context(repo_id: str) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id=repo_id,
        head_sha="head",
        as_of_ts=datetime(2026, 9, 11, tzinfo=UTC),
        capabilities=("local_scan",),
    )


@pytest.mark.asyncio
async def test_batch_resume_after_persistence_interruption() -> None:
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        lambda context: AnalyzerResult(
            analyzer_id="fixture",
            analyzer_version="1",
            status=AnalyzerStatus.PASS,
            metrics=(MetricValue(name="fixture", dimension="code", score=90, denominator=1),),
        ),
    )
    store = _Store()
    interrupted = True

    async def persist(context, results, score):
        nonlocal interrupted
        if interrupted:
            interrupted = False
            raise OSError("worker interrupted")

    orchestrator = HealthOrchestrator(analyzer_registry=registry, max_concurrency=1, max_retries=0)
    first = await orchestrator.run_repository(_context("repo"), job_store=store, persist=persist)
    assert first.status == "failed"
    assert store.rows["health-job"].state is JobState.FAILED

    resumed = await orchestrator.run_repository(
        _context("repo"), job_store=store, persist=persist, resume=True
    )
    assert resumed.status == "completed"
    assert resumed.resumed is True
    assert len(store.rows) == 1
