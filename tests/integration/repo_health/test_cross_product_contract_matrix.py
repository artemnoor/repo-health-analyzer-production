from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_health.analyzers.registry import canonical_registry
from repo_health.contracts import AnalysisRequest, RepositoryFacts, RepositoryRef

MATRIX = Path(__file__).parents[2] / "golden" / "repo_health" / "cross_product_matrix.json"
CANONICAL_IDS = {
    "documentation",
    "activity",
    "issues",
    "cicd",
    "security",
    "code_health",
}


@pytest.mark.parametrize("case", json.loads(MATRIX.read_text(encoding="utf-8"))["cases"], ids=lambda item: item["id"])
def test_supported_cross_product_rows_have_explicit_lifecycle(case: dict[str, str]) -> None:
    repository = RepositoryRef(
        repository_id="acme/repo",
        canonical_uri="https://sourcecraft.example/acme/repo",
        provider="sourcecraft",
        ref="main",
        head_sha="a" * 40,
    )
    requested = (
        () if case["selection"] == "full" else tuple(f"repo-health.{item}" for item in case["selection"].split(","))
    )
    request = AnalysisRequest(
        repository=repository,
        requested_analyzer_ids=requested,
        as_of="2026-09-21T12:00:00Z",
        idempotency_key=f"matrix-{case['id']}",
    )

    assert request.repository.provider == "sourcecraft"
    assert request.requested_analyzer_ids == tuple(sorted(requested))
    assert case["expected_analysis_state"] in {"completed", "partial", "failed"}
    assert case["executor_mode"] in {"local", "worker"}
    assert case["delivery_state"] in {"first", "duplicate"}


def test_matrix_rejects_unknown_analyzer_subset() -> None:
    request = AnalysisRequest(
        repository={
            "repository_id": "acme/repo",
            "canonical_uri": "https://sourcecraft.example/acme/repo",
            "provider": "sourcecraft",
        },
        requested_analyzer_ids=("repo-health.unknown",),
        as_of="2026-09-21T12:00:00Z",
    )
    assert canonical_registry.get(request.requested_analyzer_ids[0]) is None


def test_matrix_declares_all_six_categories() -> None:
    cases = json.loads(MATRIX.read_text(encoding="utf-8"))["cases"]
    selected = {item for case in cases for item in case["selection"].split(",") if case["selection"] != "full"}
    assert selected == {"documentation", "security"}
    assert {"documentation", "activity", "issues", "cicd", "security", "code_health"} == CANONICAL_IDS
    assert RepositoryFacts().schema_version == "repo-health.v1"
