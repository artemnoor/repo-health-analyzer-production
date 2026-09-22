"""The single production composition root for API, worker, and scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from .analyzers import CANONICAL_ANALYZER_IDS, canonical_registry, register_default_factories
from .collection import (
    CollectionService,
    SourceCraftAppSecCollector,
    SourceCraftCicdCollector,
    SourceCraftClient,
    SourceCraftIssuesCollector,
)
from .collection.code_health import GitSizerCollector, SonarQubeCollector, TodoHistoryCollector
from .collection.documentation import ValeCollector
from .collection.fallback import UnavailableFactCollector
from .collection.git import PyDrillerCollector
from .collection.sourcecraft import EnvironmentCredentialProvider
from .config import CapabilityState, CapabilityStatus, RuntimeConfig
from .contracts.results import CapabilityStatus as ContractCapabilityStatus
from .contracts.results import CollectionState, ProviderCapabilityState
from .execution import LocalExecutor, WorkerExecutor
from .infrastructure.git import GitCollector
from .orchestration import AnalysisOrchestrator
from .persistence import SQLitePersistence
from .scoring.v1 import ScoreEngineV1

log = structlog.get_logger("repo_health.runtime")


@dataclass(slots=True)
class ProductionRuntime:
    config: RuntimeConfig
    capabilities: tuple[CapabilityStatus, ...]
    persistence: SQLitePersistence
    collection: CollectionService
    orchestrator: AnalysisOrchestrator
    local_executor: LocalExecutor
    worker_executor: WorkerExecutor
    owns_persistence: bool = True
    _closed: bool = False

    @property
    def collector_source_ids(self) -> tuple[str, ...]:
        return tuple(sorted(collector.source_id for collector in self.collection.collectors))

    @property
    def analyzer_ids(self) -> tuple[str, ...]:
        return tuple(sorted(CANONICAL_ANALYZER_IDS))

    def public_capabilities(self) -> dict[str, dict[str, object]]:
        return {item.engine: item.public_dict() for item in self.capabilities}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.owns_persistence:
            self.persistence.close()


def build_production_runtime(
    config: RuntimeConfig | None = None,
    *,
    mode: Literal["api", "worker"] = "api",
    persistence: SQLitePersistence | None = None,
) -> ProductionRuntime:
    """Construct the canonical runtime; mode changes only executor selection."""

    if mode not in {"api", "worker"}:
        raise ValueError(f"unsupported production runtime mode: {mode!r}")
    config = config or RuntimeConfig.from_environment()
    capabilities = config.capability_report()
    store = persistence or SQLitePersistence(config.db_path)
    owns_persistence = persistence is None
    collectors = _build_collectors(config, capabilities)
    collection = CollectionService(collectors, capability_states=_contract_capabilities(capabilities))

    register_default_factories()
    factories = {
        analyzer_id: canonical_registry.get(analyzer_id)[1]  # type: ignore[index]
        for analyzer_id in CANONICAL_ANALYZER_IDS
    }
    local = LocalExecutor({key: value for key, value in factories.items() if value is not None})
    worker = WorkerExecutor(persistence=store, local=local, worker_id=config.worker_id)
    executor = worker if mode == "worker" else local
    orchestrator = AnalysisOrchestrator(
        collection=collection,
        persistence=store,
        executor=executor,
        score_engine=ScoreEngineV1(),
    )
    runtime = ProductionRuntime(
        config=config,
        capabilities=capabilities,
        persistence=store,
        collection=collection,
        orchestrator=orchestrator,
        local_executor=local,
        worker_executor=worker,
        owns_persistence=owns_persistence,
    )
    log.info(
        "production_runtime_built",
        mode=mode,
        collector_ids=runtime.collector_source_ids,
        analyzer_ids=runtime.analyzer_ids,
        capability_states={item.engine: item.state.value for item in capabilities},
    )
    return runtime


def _build_collectors(config: RuntimeConfig, capabilities: tuple[CapabilityStatus, ...]):
    capability_map = {item.engine: item for item in capabilities}
    collectors = [
        GitCollector(),
        PyDrillerCollector(),
        ValeCollector(executable=config.vale_path, config_path=config.vale_config_path),
        TodoHistoryCollector(),
        GitSizerCollector(executable=config.git_sizer_path),
    ]

    sonar = capability_map["sonarqube"]
    if sonar.state is CapabilityState.AVAILABLE:
        collectors.append(
            SonarQubeCollector(
                base_url=config.sonar_url,
                credentials=EnvironmentCredentialProvider("SONAR_TOKEN"),
            )
        )
    else:
        collectors.append(
            UnavailableFactCollector(
                source_id="sonarqube",
                fact_group="code_health",
                state=CollectionState.UNAVAILABLE,
                reason=sonar.reason,
            )
        )

    sourcecraft = capability_map["sourcecraft"]
    if sourcecraft.state is CapabilityState.AVAILABLE:
        client = SourceCraftClient(
            base_url=config.sourcecraft_url or "",
            credentials=EnvironmentCredentialProvider(),
        )
        collectors.extend(
            (
                SourceCraftIssuesCollector(client=client),
                SourceCraftCicdCollector(client=client),
            )
        )
        collectors.append(SourceCraftAppSecCollector(client=client))
    else:
        for source_id, fact_group in (
            ("sourcecraft.issues", "issues"),
            ("sourcecraft.cicd", "cicd"),
            ("sourcecraft.appsec", "security"),
        ):
            collectors.append(
                UnavailableFactCollector(
                    source_id=source_id,
                    fact_group=fact_group,
                    state=CollectionState.UNAVAILABLE,
                    reason=sourcecraft.reason,
                )
            )
    return tuple(collectors)


def _contract_capabilities(capabilities: tuple[CapabilityStatus, ...]) -> tuple[ContractCapabilityStatus, ...]:
    return tuple(
        ContractCapabilityStatus(
            capability_id=item.engine,
            state=ProviderCapabilityState(item.state.value),
            reason=item.reason,
        )
        for item in capabilities
    )


__all__ = ["ProductionRuntime", "build_production_runtime"]
