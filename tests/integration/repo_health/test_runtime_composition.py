"""Production composition root parity and degradation gates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from repo_health.collection.service import CollectionService
from repo_health.config import CapabilityState, RuntimeConfig
from repo_health.contracts.requests import (
    AnalysisRequest,
    AssessmentProfile,
    AuthorizationContext,
    RepositoryRef,
    SourceCraftAccessState,
)
from repo_health.contracts.results import IssuesFacts, RepositoryFacts
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


class _OwnerIssuesCollector:
    source_id = "sourcecraft.issues"
    provider = "sourcecraft"
    fact_group = "issues"

    def collect(self, repository, *, context):
        del context
        return RepositoryFacts(repository=repository, issues=IssuesFacts(available=True, observations=()))


class _GitCollector:
    source_id = "git"
    provider = "git"
    fact_group = "git"

    def collect(self, repository, *, context):
        del context
        return RepositoryFacts(repository=repository)


@pytest.mark.asyncio
async def test_public_profile_excludes_owner_sourcecraft_facts_but_owner_profile_allows_them(tmp_path) -> None:
    repository = RepositoryRef(
        repository_id="team/profile",
        canonical_uri="https://sourcecraft.example/team/profile",
        provider="sourcecraft",
    )
    collection = CollectionService((_OwnerIssuesCollector(), _GitCollector()))
    public = await collection.collect(
        AnalysisRequest(repository=repository, as_of=datetime(2026, 1, 1, tzinfo=UTC)),
        checkout_path=tmp_path,
    )
    owner = await collection.collect(
        AnalysisRequest(
            repository=repository,
            assessment_profile=AssessmentProfile.OWNER_EXTENDED,
            authorization_context=AuthorizationContext(
                identity_subject="yandex-user-42",
                sourcecraft_access=SourceCraftAccessState.AUTHORIZED,
            ),
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        checkout_path=tmp_path,
    )

    assert public.issues.available is False
    assert any(item.code == "assessment.public_sourcecraft_excluded" for item in public.limitations)
    assert "sourcecraft.issues" not in public.used_sources
    assert owner.issues.available is True
