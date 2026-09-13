import json
from datetime import UTC, datetime

import pytest

from repowise.core.persistence.models import HealthScoreProjection, RepositoryHealthSnapshot
from repowise.server.routers.code_health.canonical import build_canonical_health_report
from repowise.server.schemas.code_health import (
    CanonicalHealthReport,
    CanonicalHealthScoreProjectionResponse,
)
from tests.unit.persistence.helpers import insert_repo


@pytest.mark.asyncio
async def test_canonical_reads_the_materialized_score_projection(session) -> None:
    repo = await insert_repo(session, name="projected-health")
    as_of = datetime(2026, 9, 10, tzinfo=UTC)
    snapshot = RepositoryHealthSnapshot(
        repository_id=repo.id,
        head_sha="a" * 40,
        analyzed_at=as_of,
        as_of_ts=as_of,
        config_digest="config",
        analyzer_versions_digest="analyzers",
        score_config_digest="score",
        scope="all",
        mode="full",
        status="warn",
        score=73,
        confidence=0.8,
        evidence_coverage=0.7,
        diagnostics_json="{}",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        HealthScoreProjection(
            snapshot_id=snapshot.id,
            score_config_digest="score",
            overall_score=73,
            dimensions_json=json.dumps({"code": 73, "security": None}),
            breakdown_json=json.dumps([{"dimension": "code", "score": 73}]),
            configured_weight=1,
            available_weight=0.25,
            confidence=0.8,
            coverage=0.25,
            evidence_coverage=0.7,
            status="warn",
            limitations_json=json.dumps([]),
            score_recomputed=True,
        )
    )
    await session.commit()

    payload = await build_canonical_health_report(session, repo.id, snapshot_id=snapshot.id)

    assert payload is not None
    assert payload["score_projection"]["overall_score"] == 73
    assert payload["meta"]["score_recomputed"] is True
    assert {row["dimension"] for row in payload["dimensions"]} == {"code", "security"}


def _canonical_payload(score: float | None, *, include_projection: bool = True) -> dict:
    payload = {
        "schema_version": 1,
        "repository_id": "repo-1",
        "snapshot": {"id": "snapshot-1", "score": 9.1},
        "dimensions": [],
        "metrics": [],
        "findings": [],
        "recommendations": [],
        "analyzers": [],
        "coverage": {},
        "limitations": [],
        "criticality": {},
        "meta": {},
    }
    if include_projection:
        payload["score_projection"] = {
            "id": "projection-1",
            "score_config_digest": "digest",
            "overall_score": score,
            "dimensions": {"code": score},
            "breakdown": [{"dimension": "code", "score": score}],
            "configured_weight": 1,
            "available_weight": 1,
            "confidence": 0.9,
            "coverage": 1,
            "evidence_coverage": 1,
            "status": "pass",
            "limitations": [],
            "score_recomputed": False,
        }
    return payload


@pytest.mark.parametrize("score", [82.5, 0, None])
def test_canonical_projection_is_typed_and_keeps_zero_distinct_from_unavailable(score) -> None:
    report = CanonicalHealthReport.model_validate(_canonical_payload(score))

    assert isinstance(report.score_projection, CanonicalHealthScoreProjectionResponse)
    assert report.score_projection.overall_score == score
    assert report.snapshot["score"] == 9.1


def test_missing_projection_remains_unavailable_without_legacy_fallback() -> None:
    report = CanonicalHealthReport.model_validate(_canonical_payload(None, include_projection=False))

    assert report.score_projection is None
    assert report.snapshot["score"] == 9.1
