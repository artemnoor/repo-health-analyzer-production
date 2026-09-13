import json
from datetime import UTC, datetime, timedelta

import pytest

from repowise.core.analysis.health.ranking_projection import (
    RankingCandidate,
    evaluate_eligibility,
    rank_candidates,
)
from repowise.core.persistence.crud.analysis.health_ranking import publish_health_ranking
from repowise.core.persistence.models import HealthScoreProjection, RepositoryHealthSnapshot
from tests.unit.persistence.helpers import insert_repo


@pytest.mark.asyncio
async def test_public_ranking_is_public_safe_and_deterministic(client, session) -> None:
    now = datetime.now(UTC)
    repo = await insert_repo(session, name="public-ranked", visibility="public")
    snapshot = RepositoryHealthSnapshot(
        repository_id=repo.id,
        head_sha="a" * 40,
        analyzed_at=now,
        as_of_ts=now,
        config_digest="config",
        analyzer_versions_digest="analyzers",
        score_config_digest="score",
        scope="all",
        mode="full",
        status="pass",
        score=88,
        confidence=0.9,
        evidence_coverage=0.8,
        stale_after_ts=now + timedelta(days=1),
        diagnostics_json="{}",
    )
    session.add(snapshot)
    await session.flush()
    projection = HealthScoreProjection(
        snapshot_id=snapshot.id,
        score_config_digest="score",
        overall_score=88,
        dimensions_json=json.dumps({"code": 90, "security": 80}),
        breakdown_json="[]",
        configured_weight=1,
        available_weight=1,
        confidence=0.9,
        coverage=1,
        evidence_coverage=0.8,
        status="pass",
        limitations_json="[]",
    )
    session.add(projection)
    await session.flush()
    await publish_health_ranking(session, repo.id, snapshot, projection, now=now)
    await session.commit()

    response = await client.get("/api/health/ranking")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["overall_score"] == 88
    assert payload["items"][0]["band"] == "good"
    assert payload["facets"] == {
        "dimensions": ["code", "security"],
        "languages": [],
        "statuses": ["pass"],
    }
    assert "local_path" not in payload["items"][0]
    assert "raw_payload_ref" not in payload["items"][0]


def test_eligibility_and_tie_break_are_explicit() -> None:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    base = dict(
        url="",
        visibility="public",
        snapshot_id="s",
        score_config_digest="cfg",
        overall_score=80,
        status="pass",
        confidence=0.8,
        coverage=1.0,
        evidence_coverage=0.8,
        analyzed_at=now,
        mode="full",
        eligible=True,
    )
    candidates = [
        RankingCandidate(repository_id="b", name="Beta", **base),
        RankingCandidate(repository_id="a", name="Alpha", **base),
    ]
    assert evaluate_eligibility(candidates[0], now=now).eligible
    page, total = rank_candidates(candidates, page=1, limit=1)
    assert total == 2
    assert page[0].repository_id == "a"
