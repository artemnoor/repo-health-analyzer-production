"""Backend-only REST allowlist smoke tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from repo_health.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("REPO_HEALTH_DB", str(tmp_path / "api.sqlite3"))
    with TestClient(create_app()) as test_client:
        yield test_client


def test_api_exposes_health_and_sourcecraft_status_without_frontend_routes(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert "token_present" in ready.json()["sourcecraft"]
    assert client.get("/integrations/sourcecraft/status").status_code == 200
    assert client.get("/chat").status_code == 404


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
