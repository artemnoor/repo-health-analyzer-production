"""Production composition root parity and degradation gates."""

from __future__ import annotations

from repo_health.config import CapabilityState, RuntimeConfig
from repo_health.persistence import SQLitePersistence
from repo_health.runtime import build_production_runtime


def test_api_and_worker_modes_share_collectors_capabilities_and_analyzers() -> None:
    config = RuntimeConfig.from_environment({"VALE_PATH": "missing-vale", "GIT_SIZER_PATH": "missing-sizer"})
    api = build_production_runtime(config, mode="api", persistence=SQLitePersistence(":memory:"))
    worker = build_production_runtime(config, mode="worker", persistence=SQLitePersistence(":memory:"))
    try:
        assert api.collector_source_ids == worker.collector_source_ids
        assert api.analyzer_ids == worker.analyzer_ids
        assert api.public_capabilities() == worker.public_capabilities()
        assert api.config.digest() == worker.config.digest()
        assert type(api.orchestrator.executor).__name__ == "LocalExecutor"
        assert type(worker.orchestrator.executor).__name__ == "WorkerExecutor"
    finally:
        api.close()
        worker.close()


def test_optional_sourcecraft_and_sonar_degrade_to_explicit_collectors() -> None:
    config = RuntimeConfig.from_environment({"SOURCECRAFT_URL": "https://sourcecraft.example"})
    runtime = build_production_runtime(config, persistence=SQLitePersistence(":memory:"))
    try:
        capabilities = {item.engine: item for item in runtime.capabilities}
        assert capabilities["sourcecraft"].state is CapabilityState.MISCONFIGURED
        assert capabilities["sonarqube"].state is CapabilityState.UNAVAILABLE
        assert "sourcecraft.issues" in runtime.collector_source_ids
        assert "sourcecraft.cicd" in runtime.collector_source_ids
        assert "sourcecraft.appsec" in runtime.collector_source_ids
    finally:
        runtime.close()
