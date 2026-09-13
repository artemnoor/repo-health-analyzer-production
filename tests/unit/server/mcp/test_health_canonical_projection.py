"""MCP canonical-health projection parity."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from repowise.core.persistence.models import (
    HealthAggregate,
    HealthRecommendation,
    HealthScoreProjection,
    RepositoryHealthSnapshot,
)


@pytest.mark.asyncio
async def test_get_health_can_return_the_same_persisted_canonical_shape(
    setup_mcp, session
) -> None:
    as_of = datetime(2026, 9, 10, 12, tzinfo=UTC)
    snapshot = RepositoryHealthSnapshot(
        repository_id=setup_mcp,
        head_sha="b" * 40,
        analyzed_at=as_of,
        as_of_ts=as_of,
        config_digest="config-mcp",
        analyzer_versions_digest="analyzers-mcp",
        score_config_digest="score-mcp",
        scope="all",
        mode="full",
        status="pass",
        score=9.1,
        confidence=1.0,
        evidence_coverage=1.0,
        criticality=0.4,
        diagnostics_json=json.dumps({"source_order": "raw-normalized-derived"}),
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        HealthAggregate(
            snapshot_id=snapshot.id,
            score_config_digest="score-mcp",
            scope="all",
            dimension="repowise",
            name="repowise.health",
            value=9.1,
            score=9.1,
            evidence_coverage=1.0,
            criticality=0.4,
            provenance_json="[]",
        )
    )
    session.add(
        HealthScoreProjection(
            snapshot_id=snapshot.id,
            score_config_digest="score-mcp",
            overall_score=82.5,
            dimensions_json=json.dumps({"code": 82.5, "security": None}),
            breakdown_json=json.dumps([{"dimension": "code", "score": 82.5}]),
            configured_weight=1.0,
            available_weight=0.75,
            confidence=0.88,
            coverage=0.75,
            evidence_coverage=0.8,
            status="warn",
            limitations_json=json.dumps([{"reason": "security unavailable", "kind": "partial"}]),
            score_recomputed=False,
        )
    )
    session.add(
        HealthRecommendation(
            snapshot_id=snapshot.id,
            recommendation_id="rec-mcp",
            finding_id="finding-mcp",
            subject="Security coverage",
            dimension="security",
            finding_status="open",
            severity="high",
            reason="Security data is incomplete.",
            remediation="Run the security analyzer.",
            location_json=json.dumps({"path": "src/security.py", "line_start": 12}),
            priority=0.8,
            lifecycle="open",
            benefit=0.8,
            confidence=0.7,
            criticality=0.4,
            effort=0.2,
            risk=0.1,
            blast_radius=0.1,
            evidence_json="[]",
        )
    )
    await session.commit()

    from repowise.server.mcp_server import get_health

    output = await get_health(
        include=["canonical"],
        only=["canonical"],
        snapshot_id=snapshot.id,
        include_evidence=True,
    )
    assert output["mode"] == "canonical"
    assert output["canonical"]["snapshot"]["id"] == snapshot.id
    assert output["canonical"]["snapshot"]["score"] == 9.1
    assert output["canonical"]["score_projection"]["overall_score"] == 82.5
    assert output["canonical"]["score_projection"]["score_config_digest"] == "score-mcp"
    assert output["canonical"]["score_projection"]["dimensions"] == {"code": 82.5, "security": None}
    assert output["canonical"]["score_projection"]["limitations"] == [
        {
            "reason": "security unavailable",
            "kind": "partial",
            "affected_scope": None,
            "evidence_refs": [],
        }
    ]
    assert output["canonical"]["recommendations"][0]["remediation"] == "Run the security analyzer."
    assert output["canonical"]["meta"]["score_recomputed"] is False
