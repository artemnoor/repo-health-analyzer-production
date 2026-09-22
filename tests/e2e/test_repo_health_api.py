"""Backend-only REST allowlist smoke tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from repo_health.api.app import create_app
from repo_health.collection.service import CollectionService
from repo_health.contracts.results import RepositoryFacts
from repo_health.orchestration import AnalysisOrchestrator
from repo_health.persistence import SQLitePersistence


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("REPO_HEALTH_DB", str(tmp_path / "api.sqlite3"))
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def completed_client() -> TestClient:
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
    try:
        with TestClient(create_app(orchestrator=orchestrator, persistence=store)) as test_client:
            yield test_client
    finally:
        store.close()


def test_api_exposes_health_and_sourcecraft_status_without_frontend_routes(client: TestClient) -> None:
    health = client.get("/healthz", headers={"X-Correlation-ID": "corr-e2e"})
    assert health.status_code == 200
    assert health.headers["X-Correlation-ID"] == "corr-e2e"
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert "token_present" in ready.json()["sourcecraft"]
    assert "capabilities" in ready.json()
    assert {"vale", "pydriller", "sonarqube", "git-sizer", "sourcecraft"} <= set(ready.json()["capabilities"])
    assert client.get("/integrations/sourcecraft/status").status_code == 200
    assert client.get("/chat").status_code == 404
    assert client.get("/analyses/missing").status_code == 404


def test_api_repository_registration_and_analysis_are_contract_valid(client: TestClient) -> None:
    repository = {
        "repository_id": "team/repository",
        "canonical_uri": "https://sourcecraft.example/team/repository",
        "provider": "sourcecraft",
        "ref": "main",
    }
    response = client.post("/repositories", json=repository)
    assert response.status_code == 201
    accepted = client.post(
        "/analyses", json={"repository": repository, "idempotency_key": f"api-request-{uuid.uuid4().hex}"}
    )
    assert accepted.status_code == 202
    analysis_id = accepted.json()["analysis_id"]
    assert client.get(f"/analyses/{analysis_id}").status_code == 200
    assert client.get(f"/analyses/{analysis_id}/result").status_code in {200, 202}


def test_api_does_not_accept_owner_extended_without_trusted_identity(client: TestClient) -> None:
    repository = {
        "repository_id": "team/owner-profile",
        "canonical_uri": "https://sourcecraft.example/team/owner-profile",
        "provider": "sourcecraft",
    }

    response = client.post(
        "/analyses",
        json={
            "repository": repository,
            "assessment_profile": "owner_extended",
            "idempotency_key": "owner-profile-without-auth",
        },
    )

    assert response.status_code == 422


def test_api_persists_completed_result_with_six_categories(completed_client: TestClient) -> None:
    repository = {
        "repository_id": "team/completed",
        "canonical_uri": "https://sourcecraft.example/team/completed",
        "provider": "sourcecraft",
    }
    accepted = completed_client.post(
        "/analyses",
        json={"repository": repository, "idempotency_key": "completed-result-e2e"},
        headers={"X-Correlation-ID": "corr-completed"},
    )
    assert accepted.status_code == 202
    assert accepted.headers["X-Correlation-ID"] == "corr-completed"
    analysis_id = accepted.json()["analysis_id"]
    status_response = completed_client.get(f"/analyses/{analysis_id}")
    result_response = completed_client.get(f"/analyses/{analysis_id}/result")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "completed"
    assert result_response.status_code == 200
    result = result_response.json()
    assert result["score_engine_version"] == "repo-health-score-v1"
    assert {
        name
        for name in ("documentation", "activity", "issues", "cicd", "security", "code_health")
        if result[name] is not None
    } == {
        "documentation",
        "activity",
        "issues",
        "cicd",
        "security",
        "code_health",
    }
    assert "token" not in result_response.text.lower()


def test_api_analysis_idempotency_conflict_is_explicit(client: TestClient) -> None:
    repository = {
        "repository_id": "team/idempotent",
        "canonical_uri": "https://sourcecraft.example/team/idempotent",
        "provider": "sourcecraft",
    }
    key = "api-idempotency-conflict"
    assert client.post("/analyses", json={"repository": repository, "idempotency_key": key}).status_code == 202
    changed = {**repository, "ref": "release"}
    response = client.post("/analyses", json={"repository": changed, "idempotency_key": key})
    assert response.status_code == 409
    assert response.json()["detail"] == "idempotency key conflict"


def test_api_rejects_invalid_repository_reference_as_unprocessable_entity(client: TestClient) -> None:
    response = client.post(
        "/repositories",
        json={
            "repository_id": "team/credentials",
            "canonical_uri": "https://user:password@sourcecraft.example/team/repository",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid repository reference"


def test_api_reports_repository_identity_conflict_as_conflict(client: TestClient) -> None:
    repository = {
        "repository_id": "team/immutable",
        "canonical_uri": "https://sourcecraft.example/team/immutable",
        "provider": "sourcecraft",
        "head_sha": "a" * 40,
    }
    assert client.post("/repositories", json=repository).status_code == 201

    changed = {**repository, "head_sha": "b" * 40}
    response = client.post("/repositories", json=changed)
    assert response.status_code == 409
    assert response.json()["detail"] == "repository identity conflict"


def test_api_openapi_has_only_backend_route_families(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    assert "/healthz" in paths
    assert "/analyses" in paths
    assert not any(
        path.startswith(prefix) for path in paths for prefix in ("/chat", "/mcp", "/c4", "/workspace", "/dead-code")
    )


def test_api_scheduler_operations_are_backend_only(client: TestClient) -> None:
    repository = {
        "repository_id": "team/scheduled",
        "canonical_uri": "https://sourcecraft.example/team/scheduled",
        "provider": "sourcecraft",
    }
    created = client.post("/scheduler/analyses", json={"repository": repository, "interval_seconds": 3600})
    assert created.status_code == 202
    assert created.json()["job_name"].startswith("analysis-")
    assert client.get("/scheduler/status").status_code == 200
