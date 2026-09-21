from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from repo_health.analyzers.harness import execute_serialized
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import (
    AnalyzerInput,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    HealthCategory,
    RepositoryFacts,
)


def analyzer_input(analyzer_id: str) -> AnalyzerInput:
    facts = RepositoryFacts()
    return AnalyzerInput(
        analysis_id="analysis-harness-1",
        repository=RepositoryRef(
            repository_id="acme/example",
            canonical_uri="https://github.com/acme/example",
            provider="github",
            ref="main",
            head_sha="a" * 40,
        ),
        analyzer_id=analyzer_id,
        analyzer_version="worker-test-v1",
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
        deadline_at=datetime(2026, 9, 20, 12, 5, tzinfo=UTC),
    )


def fixture_factory(analyzer_input: AnalyzerInput) -> CategoryResult:
    category = HealthCategory(analyzer_input.analyzer_id.removeprefix("repo-health.").replace("-", "_"))
    return CategoryResult(
        analysis_id=analyzer_input.analysis_id,
        analyzer_id=analyzer_input.analyzer_id,
        analyzer_version=analyzer_input.analyzer_version,
        category=category,
        status=CategoryStatus.PASS,
        score=50,
        coverage=Coverage(status="available", covered=1, total=1),
        confidence=Confidence(value=1, level="high"),
    )


def test_all_six_analyzers_round_trip_identically_in_process() -> None:
    for analyzer_id in (
        "repo-health.documentation",
        "repo-health.activity",
        "repo-health.issues",
        "repo-health.cicd",
        "repo-health.security",
        "repo-health.code-health",
    ):
        request = analyzer_input(analyzer_id)
        encoded = execute_serialized(request.to_json(), fixture_factory)
        assert json.loads(encoded)["analyzer_id"] == analyzer_id
        assert encoded == execute_serialized(json.loads(request.to_json()), fixture_factory)


def test_subprocess_harness_matches_in_process_json() -> None:
    request = analyzer_input("repo-health.security")
    source = """
import sys
from repo_health.analyzers.harness import execute_serialized
from repo_health.contracts.results import CategoryResult, CategoryStatus, Confidence, Coverage, HealthCategory

def factory(item):
    category = HealthCategory(item.analyzer_id.removeprefix('repo-health.').replace('-', '_'))
    return CategoryResult(
        analysis_id=item.analysis_id,
        analyzer_id=item.analyzer_id,
        analyzer_version=item.analyzer_version,
        category=category,
        status=CategoryStatus.PASS,
        score=50,
        coverage=Coverage(status='available', covered=1, total=1),
        confidence=Confidence(value=1, level='high'),
    )

print(execute_serialized(sys.stdin.read(), factory), end='')
"""
    child = subprocess.run(
        [sys.executable, "-c", source],
        input=request.to_json(),
        capture_output=True,
        text=True,
        check=True,
    )

    assert child.stdout == execute_serialized(request.to_json(), fixture_factory)
    assert child.stderr == ""


def test_harness_fails_closed_on_malformed_input() -> None:
    with pytest.raises((ValidationError, json.JSONDecodeError)):
        execute_serialized('{"schema_version":"repo-health.v1","raw_payload":{"token":"x"}}', fixture_factory)


def test_worker_import_does_not_load_api_database_or_legacy_integrations() -> None:
    source = (
        "import sys; import repo_health.analyzers.harness; "
        "print(any(name == 'fastapi' or name == 'sqlalchemy' or "
        "name.startswith('repo_health.api') or name.startswith('repo_health.persistence') "
        "for name in sys.modules))"
    )
    child = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, check=True)

    assert child.stdout.strip() == "False"
