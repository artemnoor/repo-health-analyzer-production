"""Local/worker execution failure isolation and parity tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repo_health.analyzers import canonical_registry, register_default_factories
from repo_health.collection.service import CollectionService
from repo_health.contracts.execution import AnalyzerTask, ResourceLimits
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.contracts.results import (
    CategoryStatus,
    RepositoryFacts,
)
from repo_health.execution.local import LocalExecutor
from repo_health.execution.worker import WorkerExecutor
from repo_health.orchestration import AnalysisOrchestrator
from repo_health.persistence import SQLitePersistence


def _repo() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _request() -> AnalysisRequest:
    return AnalysisRequest(repository=_repo(), as_of=datetime(2026, 1, 1, tzinfo=UTC), idempotency_key="execution-test")


def _task(analyzer_id: str = "repo-health.issues", *, timeout: float = 30.0) -> AnalyzerTask:
    register_default_factories()
    spec = canonical_registry.get(analyzer_id)[0]  # type: ignore[index]
    facts = RepositoryFacts(
        repository=_repo(), issues={"available": True, "observations": ({"key": "open_count", "value": 1},)}
    )
    from repo_health.contracts.results import AnalyzerInput

    input_contract = AnalyzerInput(
        analysis_id="analysis-execution",
        repository=_repo(),
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )
    return AnalyzerTask(
        analysis_id="analysis-execution",
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        category=spec.category,
        input=input_contract,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
        resource_limits=ResourceLimits(timeout_seconds=timeout),
    )


@pytest.mark.asyncio
async def test_local_executor_returns_unavailable_result_for_one_bad_analyzer() -> None:
    good = _task()
    bad = _task().model_copy(update={"task_id": "task-bad", "analyzer_id": "repo-health.issues"})

    def explode(_input):
        raise RuntimeError("fixture")

    executor = LocalExecutor({good.analyzer_id: explode})
    outcomes = await executor.execute_many((bad, good))
    assert len(outcomes) == 2
    assert all(outcome.result.status is CategoryStatus.ERROR for outcome in outcomes)
    assert [outcome.result.analyzer_id for outcome in outcomes] == ["repo-health.issues", "repo-health.issues"]


@pytest.mark.asyncio
async def test_local_executor_timeout_is_retryable_and_telemetry_cannot_escape() -> None:
    task = _task(timeout=0.01)

    async def slow(_input):
        await asyncio.sleep(1)

    class Telemetry:
        def record(self, *_args, **_kwargs):
            raise RuntimeError("telemetry fixture")

    outcome = await LocalExecutor({task.analyzer_id: slow}, telemetry=Telemetry()).execute(task)
    assert outcome.state.value == "timeout"
    assert outcome.retryable is True


@pytest.mark.asyncio
async def test_orchestrator_runs_canonical_pipeline_and_persists_result(tmp_path: Path) -> None:
    class AllFacts:
        source_id = "fixture"

        def collect(self, repository, *, context):
            del context
            groups = {
                name: {"available": True, "observations": ({"key": "score", "value": 80},)}
                for name in ("git", "documentation", "issues", "cicd", "security", "code_health")
            }
            return RepositoryFacts(
                repository=repository,
                collected_at=datetime(2026, 1, 1, tzinfo=UTC),
                source_versions={"fixture": "v1"},
                **groups,
            )

    store = SQLitePersistence()
    orchestrator = AnalysisOrchestrator(collection=CollectionService((AllFacts(),)), persistence=store)
    envelope = await orchestrator.analyze(
        _request().model_copy(update={"idempotency_key": "orchestrator-test"}), checkout_path=tmp_path
    )
    assert envelope.score is not None
    assert envelope.score.score_engine_version == "repo-health-score-v1"
    assert len(envelope.category_results) == 6
    assert store.get_analysis(envelope.analysis_id).envelope.score is not None  # type: ignore[union-attr]
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_runs_full_six_category_pipeline_through_worker_queue(tmp_path: Path) -> None:
    class AllFacts:
        source_id = "fixture"

        def collect(self, repository, *, context):
            del context
            groups = {
                name: {"available": True, "observations": ({"key": "score", "value": 80},)}
                for name in ("git", "documentation", "issues", "cicd", "security", "code_health")
            }
            return RepositoryFacts(
                repository=repository,
                collected_at=datetime(2026, 1, 1, tzinfo=UTC),
                source_versions={"fixture": "v1"},
                **groups,
            )

    store = SQLitePersistence()
    register_default_factories()
    factories = {
        analyzer_id: canonical_registry.get(analyzer_id)[1]  # type: ignore[index]
        for analyzer_id in canonical_registry.ids()
    }
    worker = WorkerExecutor(
        persistence=store,
        local=LocalExecutor({key: value for key, value in factories.items() if value is not None}),
        worker_id="worker-orchestrator",
    )
    orchestrator = AnalysisOrchestrator(collection=CollectionService((AllFacts(),)), persistence=store, executor=worker)
    envelope = await orchestrator.analyze(
        _request().model_copy(update={"idempotency_key": "worker-orchestrator-test"}), checkout_path=tmp_path
    )
    assert envelope.status.state.value == "completed"
    assert len(envelope.category_results) == 6
    assert {item.analyzer_id for item in envelope.category_results} == set(canonical_registry.ids())
    assert envelope.score is not None
    assert store.get_analysis(envelope.analysis_id).envelope.score is not None  # type: ignore[union-attr]
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_persists_partial_result_when_one_analyzer_fails(tmp_path: Path) -> None:
    class AllFacts:
        source_id = "fixture"

        def collect(self, repository, *, context):
            del context
            groups = {
                name: {"available": True, "observations": ({"key": "score", "value": 80},)}
                for name in ("git", "documentation", "issues", "cicd", "security", "code_health")
            }
            return RepositoryFacts(
                repository=repository,
                collected_at=datetime(2026, 1, 1, tzinfo=UTC),
                source_versions={"fixture": "v1"},
                **groups,
            )

    register_default_factories()
    factories = {
        analyzer_id: canonical_registry.get(analyzer_id)[1]  # type: ignore[index]
        for analyzer_id in canonical_registry.ids()
    }

    def explode(_input):
        raise RuntimeError("injected analyzer failure")

    factories["repo-health.issues"] = explode
    store = SQLitePersistence()
    orchestrator = AnalysisOrchestrator(
        collection=CollectionService((AllFacts(),)),
        persistence=store,
        executor=LocalExecutor({key: value for key, value in factories.items() if value is not None}),
    )
    request = _request().model_copy(update={"idempotency_key": "partial-analyzer-test"})
    envelope = await orchestrator.analyze(request, checkout_path=tmp_path)
    assert envelope.status.state.value == "partial"
    assert len(envelope.category_results) == 6
    failed = next(item for item in envelope.category_results if item.analyzer_id == "repo-health.issues")
    assert failed.status is CategoryStatus.ERROR
    assert sum(item.status is CategoryStatus.ERROR for item in envelope.category_results) == 1
    assert envelope.score is not None
    assert envelope.score.overall_score is None
    assert envelope.score.presentation_state == "INSUFFICIENT_DATA"
    assert envelope.score.score_status == "inconclusive"
    persisted = store.get_analysis(envelope.analysis_id)
    assert persisted is not None
    assert persisted.envelope.category_results == envelope.category_results
    store.close()


@pytest.mark.asyncio
async def test_worker_executor_reuses_serialized_task_and_matches_local_result() -> None:
    task = _task()
    register_default_factories()
    factory = canonical_registry.get(task.analyzer_id)[1]  # type: ignore[index]
    local = await LocalExecutor({task.analyzer_id: factory}).execute(task)
    store = SQLitePersistence()
    store.create_analysis(
        AnalysisRequest(
            repository=_repo(),
            analysis_id=task.analysis_id,
            as_of=datetime.now(UTC),
            idempotency_key="worker-execution",
        )
    )
    worker = WorkerExecutor(
        persistence=store,
        local=LocalExecutor({task.analyzer_id: factory}),
        worker_id="worker-test",
    )
    worker.enqueue(task)
    remote = await worker.run_once()
    assert remote is not None
    assert remote.result.to_json() == local.result.to_json()
    assert worker.renew(task.task_id) is False
    assert store.get_analysis(task.analysis_id) is not None
    store.close()
