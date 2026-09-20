from repowise.core.repo_health.worker_runtime import WorkerConfig, readiness


def test_worker_readiness_never_exposes_database_url() -> None:
    config = WorkerConfig(
        queue_backend="sql",
        database_url="postgresql://user:secret@example.test/db",
        worker_id="worker-1",
    )
    safe = config.redacted()
    state = readiness(config, database_available=True, queue_available=True)

    assert state.ready is True
    assert safe["database_configured"] is True
    assert "secret" not in str(safe)
    assert "database_url" not in safe


def test_memory_worker_does_not_claim_database_dependency() -> None:
    config = WorkerConfig(queue_backend="memory", worker_id="worker-1")
    state = readiness(config, database_available=False, queue_available=True)
    assert state.ready is True
    assert state.database == "not_required"
