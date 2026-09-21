"""Six-category execution through the real production composition root."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repo_health.config import RuntimeConfig
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.persistence import SQLitePersistence
from repo_health.runtime import build_production_runtime


def _git_fixture(path: Path) -> None:
    (path / "main.py").write_text("# TODO: keep the fixture observable\nprint('ok')\n", encoding="utf-8")
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "repo-health@example.invalid"],
        ["git", "config", "user.name", "Repo Health Test"],
        ["git", "add", "main.py"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "fixture"],
        ["git", "branch", "-M", "main"],
    ]
    for command in commands:
        subprocess.run(command, cwd=path, check=True, capture_output=True, text=True)


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        repository=RepositoryRef(
            repository_id="team/production-fixture",
            canonical_uri="https://sourcecraft.example/team/production-fixture",
            provider="sourcecraft",
            ref="main",
        ),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_production_composition_runs_all_six_categories_local_and_worker(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    config = RuntimeConfig.from_environment(
        {
            "REPO_HEALTH_DB": ":memory:",
            "REPO_HEALTH_CHECKOUT_ROOT": str(tmp_path),
            "REPO_HEALTH_WORKER_ID": "production-test-worker",
            "VALE_PATH": "missing-vale",
            "GIT_SIZER_PATH": "missing-git-sizer",
        }
    )
    request = _request()
    local = build_production_runtime(config, mode="api", persistence=SQLitePersistence(":memory:"))
    worker = build_production_runtime(config, mode="worker", persistence=SQLitePersistence(":memory:"))
    try:
        local_result = await local.orchestrator.analyze(request, checkout_path=tmp_path)
        worker_result = await worker.orchestrator.analyze(request, checkout_path=tmp_path)

        expected = {
            "repo-health.documentation",
            "repo-health.activity",
            "repo-health.issues",
            "repo-health.cicd",
            "repo-health.security",
            "repo-health.code-health",
        }
        assert {item.analyzer_id for item in local_result.category_results} == expected
        assert {item.analyzer_id for item in worker_result.category_results} == expected
        assert {item.source_id for item in local_result.facts.source_statuses} >= {
            "git",
            "pydriller",
            "vale",
            "git-sizer",
            "git.todo-history",
            "sonarqube",
            "sourcecraft.issues",
            "sourcecraft.cicd",
            "sourcecraft.appsec",
        }
        assert [item.category for item in local_result.category_results] == [
            item.category for item in worker_result.category_results
        ]
        assert [item.status for item in local_result.category_results] == [
            item.status for item in worker_result.category_results
        ]
        assert local_result.score is not None
        assert worker_result.score is not None
        assert local_result.score.overall_score == pytest.approx(worker_result.score.overall_score, abs=0.01)
        assert any(item.code == "vale.missing" for item in local_result.facts.limitations)
        assert any(item.code == "sonarqube.unavailable" for item in local_result.facts.limitations)
    finally:
        local.close()
        worker.close()
