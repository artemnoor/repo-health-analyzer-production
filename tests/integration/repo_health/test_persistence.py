"""SQLite lifecycle, idempotency and immutable-envelope integration gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from repo_health.analyzers import canonical_registry
from repo_health.contracts.execution import AnalyzerTask, ExecutionOutcome, ExecutionState
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.contracts.results import (
    AnalysisState,
    AnalysisStatus,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    HealthCategory,
    RepoHealthResult,
)
from repo_health.persistence import (
    IdempotencyConflict,
    ImmutableResultConflict,
    LeaseOwnershipError,
    PersistenceDecodeError,
    SQLitePersistence,
)


def _repo() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _request(key: str = "same-request") -> AnalysisRequest:
    return AnalysisRequest(repository=_repo(), as_of=datetime(2026, 1, 1, tzinfo=UTC), idempotency_key=key)


def _task(request: AnalysisRequest) -> AnalyzerTask:
    spec = canonical_registry.get("repo-health.issues")[0]  # type: ignore[index]
    from repo_health.contracts.results import AnalyzerInput, RepositoryFacts

    facts = RepositoryFacts(repository=_repo())
    analyzer_input = AnalyzerInput(
        analysis_id=request.analysis_id,
        repository=_repo(),
        analyzer_id=spec.id,
        analyzer_version=spec.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )
    return AnalyzerTask(
        analysis_id=request.analysis_id,
        analyzer_id=spec.id,
        analyzer_version=spec.version,
        category=HealthCategory.ISSUES,
        input=analyzer_input,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )


def test_create_analysis_is_idempotent_and_conflicting_payload_is_rejected() -> None:
    store = SQLitePersistence()
    first = store.create_analysis(_request())
    second = store.create_analysis(_request())
    assert first.analysis_id == second.analysis_id
    with pytest.raises(IdempotencyConflict):
        store.create_analysis(_request("same-request").model_copy(update={"mode": "offline"}))
    store.close()


def test_task_claim_and_commit_are_durable() -> None:
    store = SQLitePersistence()
    request = _request("task-request")
    store.create_analysis(request)
    task = _task(request)
    store.enqueue_task(task)
    claimed = store.claim_task(worker_id="worker-1", now=datetime.now(UTC), lease_seconds=30)
    assert claimed is not None
    assert claimed.lease_owner == "worker-1"
    result = CategoryResult(
        analysis_id=request.analysis_id,
        analyzer_id=task.analyzer_id,
        analyzer_version=task.analyzer_version,
        category=HealthCategory.ISSUES,
        status=CategoryStatus.SKIPPED,
        coverage=Coverage(status="unavailable"),
        confidence=Confidence(value=0.0, level="unknown"),
    )
    outcome = ExecutionOutcome(
        task_id=task.task_id,
        analysis_id=request.analysis_id,
        state=ExecutionState.COMPLETED,
        result=result,
        attempt=1,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    completed = store.complete_task(outcome, worker_id="worker-1")
    assert completed.status == "completed"
    assert completed.outcome is not None
    assert store.get_summary(request.analysis_id) is not None
    store.close()


def test_result_commit_is_immutable_and_corrupt_storage_is_rejected() -> None:
    store = SQLitePersistence()
    request = _request("immutable-request")
    store.create_analysis(request)
    envelope = store.get_analysis(request.analysis_id).envelope  # type: ignore[union-attr]
    status = AnalysisStatus(analysis_id=request.analysis_id, state=AnalysisState.COMPLETED)
    score = RepoHealthResult(
        analysis_id=request.analysis_id,
        repository=request.repository,
        status=status,
        overall_score=10.0,
        score_engine_version="repo-health-score-v1",
        presentation_state="SCORE",
        score_status="pass",
    )
    result = envelope.model_copy(update={"status": status, "score": score})
    store.commit_envelope(result)
    changed = result.model_copy(update={"score": score.model_copy(update={"overall_score": 20.0})})
    with pytest.raises(ImmutableResultConflict):
        store.commit_envelope(changed)
    store._connection.execute(
        "UPDATE analyses SET envelope = ? WHERE analysis_id = ?", ("{broken", request.analysis_id)
    )
    store._connection.commit()
    with pytest.raises(PersistenceDecodeError):
        store.get_analysis(request.analysis_id)
    store.close()


def test_retry_claim_increments_attempt_and_duplicate_task_payload_is_rejected() -> None:
    store = SQLitePersistence()
    request = _request("retry-request")
    store.create_analysis(request)
    task = _task(request)
    store.enqueue_task(task)
    with pytest.raises(IdempotencyConflict):
        store.enqueue_task(
            task.model_copy(
                update={"policy_digest": "b" * 64, "input": task.input.model_copy(update={"policy_digest": "b" * 64})}
            )
        )
    claimed = store.claim_task(worker_id="worker-1", now=datetime.now(UTC), lease_seconds=30)
    assert claimed is not None
    store.fail_task(
        task.task_id,
        worker_id="worker-1",
        retry=True,
        error="transient",
        available_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    retried = store.claim_task(worker_id="worker-2", now=datetime.now(UTC), lease_seconds=30)
    assert retried is not None
    assert retried.attempt == 2
    store.close()


def test_expired_lease_is_reclaimed_and_heartbeat_is_owner_scoped() -> None:
    store = SQLitePersistence()
    request = _request("lease-request")
    store.create_analysis(request)
    task = _task(request)
    store.enqueue_task(task)
    first_time = datetime.now(UTC)
    claimed = store.claim_task(worker_id="worker-1", now=first_time, lease_seconds=5)
    assert claimed is not None
    assert store.renew_task(task_id=task.task_id, worker_id="worker-2", now=first_time, lease_seconds=5) is False
    assert store.renew_task(task_id=task.task_id, worker_id="worker-1", now=first_time, lease_seconds=5) is True
    reclaimed = store.claim_task(worker_id="worker-2", now=first_time + timedelta(seconds=6), lease_seconds=5)
    assert reclaimed is not None
    assert reclaimed.attempt == 2
    assert reclaimed.lease_owner == "worker-2"
    result = CategoryResult(
        analysis_id=request.analysis_id,
        analyzer_id=task.analyzer_id,
        analyzer_version=task.analyzer_version,
        category=HealthCategory.ISSUES,
        status=CategoryStatus.SKIPPED,
        coverage=Coverage(status="unavailable"),
        confidence=Confidence(value=0.0, level="unknown"),
    )
    outcome = ExecutionOutcome(
        task_id=task.task_id,
        analysis_id=request.analysis_id,
        state=ExecutionState.COMPLETED,
        result=result,
        attempt=1,
        started_at=first_time,
        finished_at=first_time,
    )
    with pytest.raises(LeaseOwnershipError):
        store.complete_task(outcome, worker_id="worker-1")
    with pytest.raises(LeaseOwnershipError):
        store.fail_task(
            task.task_id,
            worker_id="worker-1",
            retry=False,
            error="stale-worker",
            available_at=first_time,
        )
    store.close()
