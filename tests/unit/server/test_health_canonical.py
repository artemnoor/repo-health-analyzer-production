"""Contract tests for the persisted canonical health projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from repowise.core.persistence.models import (
    HealthAggregate,
    HealthFindingEvidence,
    HealthMetricValue,
    HealthRecommendation,
    HealthSourceRun,
    RepositoryHealthSnapshot,
)
from repowise.server.routers.code_health.canonical import build_canonical_health_report
from tests.unit.persistence.helpers import insert_repo


async def _seed_canonical(session):
    repo = await insert_repo(session, name="canonical-health")
    as_of = datetime(2026, 9, 10, 12, tzinfo=UTC)
    snapshot = RepositoryHealthSnapshot(
        repository_id=repo.id,
        head_sha="a" * 40,
        analyzed_at=as_of,
        as_of_ts=as_of,
        config_digest="config-a",
        analyzer_versions_digest="analyzers-a",
        score_config_digest="score-a",
        scope="all",
        mode="full",
        status="warn",
        score=8.4,
        confidence=0.75,
        unknown_count=1,
        error_count=0,
        skipped_weight=0.25,
        evidence_coverage=0.5,
        criticality=0.8,
        diagnostics_json=json.dumps({"source_order": "raw-normalized-derived"}),
    )
    session.add(snapshot)
    await session.flush()
    source_run = HealthSourceRun(
        snapshot_id=snapshot.id,
        analyzer_id="fixture.security",
        source="scorecard",
        source_commit="source-a",
        tool_version="1.0",
        status="warn",
        duration_ms=12,
        raw_fact_count=2,
        diagnostic_json=json.dumps({"raw_fact_count": 2}),
        started_at=as_of,
        finished_at=as_of,
    )
    session.add(source_run)
    session.add(
        HealthMetricValue(
            snapshot_id=snapshot.id,
            analyzer_id="fixture.security",
            name="security:policy",
            value_json="true",
            numeric_value=None,
            unit="present",
            score=None,
            population=1,
            denominator=1,
            weight=1,
            available_weight=0.5,
            provenance_json=json.dumps(
                [{"source": "scorecard", "path": ".github/workflows/ci.yml"}]
            ),
        )
    )
    session.add(
        HealthAggregate(
            snapshot_id=snapshot.id,
            score_config_digest="score-a",
            scope="all",
            dimension="security",
            name="fixture.security",
            value=8.4,
            score=8.4,
            unknown_count=1,
            error_count=0,
            skipped_weight=0.25,
            evidence_coverage=0.5,
            criticality=0.8,
            provenance_json=json.dumps([{"source": "scorecard"}]),
        )
    )
    session.add(
        HealthRecommendation(
            snapshot_id=snapshot.id,
            recommendation_id="rec:security-1",
            finding_id="finding-security-1",
            subject=".github/workflows/ci.yml",
            dimension="security",
            finding_status="open",
            severity="high",
            reason="Workflow permissions are broad.",
            remediation="Set least-privilege permissions.",
            location_json=json.dumps({"path": ".github/workflows/ci.yml", "line_start": 4}),
            priority=0.9,
            lifecycle="new",
            benefit=3,
            confidence=0.9,
            criticality=0.8,
            effort=1,
            risk=1,
            blast_radius=1,
            raw_impact=3,
            applied_impact=3,
            evidence_json=json.dumps([]),
            first_seen_at=as_of,
            last_seen_at=as_of,
        )
    )
    session.add(
        HealthFindingEvidence(
            snapshot_id=snapshot.id,
            finding_id="finding-security-1",
            analyzer_id="fixture.security",
            source="scorecard",
            source_commit="source-a",
            tool_version="1.0",
            path=".github/workflows/ci.yml",
            line_start=4,
            line_end=4,
            json_pointer="/permissions",
            confidence=0.9,
            redaction="partial",
            raw_ref="raw://scorecard/event-1",
            collected_at=as_of,
        )
    )
    await session.commit()
    return repo, snapshot


@pytest.mark.asyncio
async def test_canonical_read_model_is_rest_mcp_safe_and_evidence_opt_in(
    session, client: AsyncClient
) -> None:
    repo, snapshot = await _seed_canonical(session)

    expected = await build_canonical_health_report(
        session,
        repo.id,
        snapshot_id=snapshot.id,
        dimension="security",
        severity="high",
        subject="workflow",
        include_evidence=False,
    )
    assert expected is not None
    assert expected["snapshot"]["score"] == 8.4
    assert expected["criticality"] == {
        "score": 0.8,
        "applied_to_score": False,
        "used_for_recommendation_priority": True,
    }
    assert expected["meta"]["score_recomputed"] is False
    assert expected["findings"][0]["evidence"]["count"] == 1
    assert "refs" not in expected["findings"][0]["evidence"]

    response = await client.get(
        f"/api/repos/{repo.id}/health/canonical",
        params={
            "snapshot": snapshot.id,
            "dimension": "security",
            "severity": "high",
            "subject": "workflow",
        },
    )
    assert response.status_code == 200
    assert response.json() == expected

    detailed = await client.get(
        f"/api/repos/{repo.id}/health/canonical",
        params={"snapshot": snapshot.id, "include_evidence": "true"},
    )
    assert detailed.status_code == 200
    assert detailed.json()["findings"][0]["evidence"]["refs"][0]["raw_ref"].startswith(
        "raw://"
    )


@pytest.mark.asyncio
async def test_canonical_missing_snapshot_is_explicit(client: AsyncClient, session) -> None:
    repo = await insert_repo(session, name="without-canonical-health")
    response = await client.get(f"/api/repos/{repo.id}/health/canonical")
    assert response.status_code == 404
    assert "Persisted health snapshot" in response.json()["detail"]
