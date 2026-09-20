
import pytest

from repowise.core.repo_health.analyzers.documentation import bind_documentation_analyzer
from repowise.core.repo_health.contracts import (
    AnalyzerInput,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    DocumentationFacts,
    HealthCategory,
    RepositoryFacts,
    RepositoryRef,
)
from repowise.core.repo_health.execution import (
    AnalyzerTask,
    ExecutionState,
    InMemoryQueue,
    InMemoryTelemetry,
    LocalExecutor,
    RetryableExecutionError,
    WorkerExecutor,
)


def _task(*, timeout_seconds: float = 1.0) -> AnalyzerTask:
    repository = RepositoryRef(
        repository_id="repo-1",
        canonical_uri="https://example.test/acme/repo",
        provider="github",
        head_sha="a" * 40,
    )
    facts = RepositoryFacts(repository=repository, documentation=DocumentationFacts(available=True))
    analyzer_input = AnalyzerInput(
        analysis_id="analysis-1",
        repository=repository,
        analyzer_id="repo-health.documentation",
        analyzer_version="repo-health-documentation-v1",
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )
    return AnalyzerTask(
        analysis_id="analysis-1",
        analyzer_id=analyzer_input.analyzer_id,
        analyzer_version=analyzer_input.analyzer_version,
        category=HealthCategory.DOCUMENTATION,
        input=analyzer_input,
        facts_digest=analyzer_input.facts_digest,
        policy_digest=analyzer_input.policy_digest,
        resource_limits={"timeout_seconds": timeout_seconds},
    )


def _factory(value: float = 91.0):
    def evaluate(_input):
        return CategoryResult(
            analysis_id="analysis-1",
            analyzer_id="repo-health.documentation",
            analyzer_version="repo-health-documentation-v1",
            category=HealthCategory.DOCUMENTATION,
            status=CategoryStatus.PASS,
            score=value,
            coverage=Coverage(status="available", covered=1, total=1),
            confidence=Confidence(value=1.0, level="high"),
        )

    return bind_documentation_analyzer(evaluate, lambda result, **_: result)


@pytest.mark.asyncio
async def test_local_executor_task_id_and_result_are_deterministic() -> None:
    task = _task()
    repeated = _task()
    assert task.task_id == repeated.task_id
    outcome = await LocalExecutor({task.analyzer_id: _factory()}).execute(task)
    assert outcome.state is ExecutionState.COMPLETED
    assert outcome.result.score == 91.0
    repeated_outcome = await LocalExecutor({task.analyzer_id: _factory()}).execute(repeated)
    assert outcome.task_id == repeated_outcome.task_id
    assert outcome.result == repeated_outcome.result


@pytest.mark.asyncio
async def test_local_executor_isolates_timeout_as_retryable_error() -> None:
    task = _task(timeout_seconds=0.01)

    def slow(_input):
        import time

        time.sleep(0.05)
        return _factory()(_input)

    outcome = await LocalExecutor({task.analyzer_id: slow}).execute(task)
    assert outcome.state is ExecutionState.TIMEOUT
    assert outcome.retryable is True
    assert outcome.result.status is CategoryStatus.ERROR


@pytest.mark.asyncio
async def test_queue_retry_increments_attempt_and_ack_is_explicit() -> None:
    queue = InMemoryQueue()
    task = _task()
    await queue.publish(task, max_attempts=2)
    await queue.publish(task, max_attempts=2)

    first = await queue.claim("worker-1")
    assert first is not None
    assert first.attempt == 1
    await queue.retry(task.task_id, "worker-1", reason="transient", delay_seconds=0)

    second = await queue.claim("worker-2")
    assert second is not None
    assert second.attempt == 2
    await queue.ack(task.task_id, "worker-2")
    assert await queue.claim("worker-3") is None


@pytest.mark.asyncio
async def test_worker_persists_before_ack_and_retries_transient_failure() -> None:
    queue = InMemoryQueue()
    task = _task()
    await queue.publish(task, max_attempts=2)
    calls = 0
    persisted = []

    def flaky(analyzer_input):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableExecutionError("test-only transient")
        return _factory()(analyzer_input)

    class Writer:
        async def persist(self, outcome):
            persisted.append(outcome)

    worker = WorkerExecutor(
        queue,
        LocalExecutor({task.analyzer_id: flaky}),
        Writer(),
        worker_id="worker-1",
        retry_delay_seconds=0,
    )
    first = await worker.run_once()
    assert first is not None and first.retryable is True
    assert persisted == []
    second = await worker.run_once()
    assert second is not None and second.state is ExecutionState.COMPLETED
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_execution_telemetry_is_correlated_and_redacted() -> None:
    telemetry = InMemoryTelemetry()
    task = _task()
    executor = LocalExecutor.configured(
        {task.analyzer_id: _factory()}, max_concurrency=1, telemetry=telemetry
    )
    outcome = await executor.execute(task)

    assert outcome.state is ExecutionState.COMPLETED
    assert len(telemetry.events) == 1
    event, fields = telemetry.events[0]
    assert event == "repo_health_analyzer_finished"
    assert fields["analysis_id"] == "analysis-1"
    assert "token" not in fields
