"""Serialized local/subprocess analyzer boundary tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime

from repo_health.analyzers import canonical_registry, register_default_factories
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import (
    AnalyzerInput,
    CicdFacts,
    CodeHealthFacts,
    DocumentationFacts,
    GitFacts,
    IssuesFacts,
    RepositoryFacts,
    SecurityFacts,
)


def test_serialized_worker_returns_category_result_without_api_imports() -> None:
    analyzer_id = "repo-health.issues"
    spec = canonical_registry.get(analyzer_id)[0]  # type: ignore[index]
    repository = RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )
    facts = RepositoryFacts(
        repository=repository,
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
        issues=IssuesFacts(available=True, observations=({"key": "open_count", "value": 1},)),
    )
    payload = AnalyzerInput(
        analysis_id="process-analysis",
        repository=repository,
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    ).to_json()
    result = subprocess.run(
        [sys.executable, "-m", "repo_health.analyzers.worker", "--analyzer", analyzer_id],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    decoded = json.loads(result.stdout)
    assert decoded["analyzer_id"] == analyzer_id
    assert "fastapi" not in result.stdout.casefold()


def test_all_six_analyzers_have_local_and_subprocess_result_parity() -> None:
    register_default_factories()
    groups = {
        "repo-health.documentation": DocumentationFacts(
            available=True,
            observations=(
                {"key": "file_count", "value": 1},
                {"key": "words", "value": 1000},
                {"key": "completeness", "value": 100},
                {"key": "instructions", "value": 100},
                {"key": "readability", "value": 100},
                {"key": "vale_quality", "value": 100},
            ),
        ),
        "repo-health.activity": GitFacts(available=True, observations=({"key": "commit_count", "value": 5},)),
        "repo-health.issues": IssuesFacts(available=True, observations=({"key": "open_count", "value": 1},)),
        "repo-health.cicd": CicdFacts(
            available=True,
            observations=(
                {"key": "run_count", "value": 5},
                {"key": "failure_rate", "value": 0.0},
                {"key": "failure_streak", "value": 0},
                {"key": "p50_seconds", "value": 1},
                {"key": "p95_seconds", "value": 1},
            ),
        ),
        "repo-health.security": SecurityFacts(available=True, observations=({"key": "active_count", "value": 0},)),
        "repo-health.code-health": CodeHealthFacts(
            available=True,
            observations=(
                {"key": "ncloc", "value": 100},
                {"key": "maintainability_rating", "value": "A"},
            ),
        ),
    }
    repository = RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )
    for analyzer_id, group in groups.items():
        spec = canonical_registry.get(analyzer_id)[0]  # type: ignore[index]
        facts = RepositoryFacts(
            repository=repository, collected_at=datetime(2026, 1, 1, tzinfo=UTC), **{spec.fact_group: group}
        )
        analyzer_input = AnalyzerInput(
            analysis_id="parity-analysis",
            repository=repository,
            analyzer_id=analyzer_id,
            analyzer_version=spec.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest="a" * 64,
        )
        local = canonical_registry.run(analyzer_id, analyzer_input).model_dump(mode="json")
        process = subprocess.run(
            [sys.executable, "-m", "repo_health.analyzers.worker", "--analyzer", analyzer_id],
            input=analyzer_input.to_json(),
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(process.stdout) == local
