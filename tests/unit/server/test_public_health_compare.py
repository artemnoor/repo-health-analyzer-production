import json
from datetime import UTC, datetime, timedelta

import pytest

from repowise.core.persistence.crud.analysis.health_ranking import publish_health_ranking
from repowise.core.persistence.models import HealthScoreProjection, RepositoryHealthSnapshot
from tests.unit.persistence.helpers import insert_repo


async def _publish_ranking_row(
    session,
    *,
    name: str,
    score: float | None,
    analyzed_at: datetime,
    stale_after_ts: datetime | None,
    now: datetime,
    visibility: str = "public",
    evidence_coverage: float = 0.8,
):
    repo = await insert_repo(
        session,
        name=name,
        local_path=f"/tmp/{name}",
        visibility=visibility,
    )
    snapshot = RepositoryHealthSnapshot(
        repository_id=repo.id,
        head_sha=(name.encode().hex() * 40)[:40],
        analyzed_at=analyzed_at,
        as_of_ts=analyzed_at,
        config_digest="config",
        analyzer_versions_digest="analyzers",
        score_config_digest="score",
        scope="all",
        mode="full",
        status="pass" if score is not None else "inconclusive",
        score=score,
        confidence=0.9,
        evidence_coverage=evidence_coverage,
        stale_after_ts=stale_after_ts,
        diagnostics_json="{}",
    )
    session.add(snapshot)
    await session.flush()
    projection = HealthScoreProjection(
        snapshot_id=snapshot.id,
        score_config_digest="score",
        overall_score=score,
        dimensions_json=json.dumps({"code": score}),
        breakdown_json="[]",
        configured_weight=1,
        available_weight=1 if score is not None else 0,
        confidence=0.9,
        coverage=1 if score is not None else 0,
        evidence_coverage=evidence_coverage,
        status="pass" if score is not None else "inconclusive",
        limitations_json="[]",
    )
    session.add(projection)
    await session.flush()
    await publish_health_ranking(session, repo.id, snapshot, projection, now=now)
    return repo


@pytest.mark.asyncio
async def test_public_compare_is_bounded_and_excludes_private_rows(client, session) -> None:
    now = datetime.now(UTC)
    public_rows = []
    for index, score in enumerate((91, 72)):
        repo = await insert_repo(
            session,
            name=f"public-{index}",
            local_path=f"/tmp/public-{index}",
            visibility="public",
        )
        snapshot = RepositoryHealthSnapshot(
            repository_id=repo.id,
            head_sha=f"{index + 1:x}" * 40,
            analyzed_at=now - timedelta(minutes=index),
            as_of_ts=now - timedelta(minutes=index),
            config_digest="config",
            analyzer_versions_digest="analyzers",
            score_config_digest="score",
            scope="all",
            mode="full",
            status="pass",
            score=score,
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
            overall_score=score,
            dimensions_json=json.dumps({"code": score}),
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
        public_rows.append(repo)

    private = await insert_repo(
        session,
        name="private",
        local_path="/tmp/private-ranking",
        visibility="private",
    )
    await session.commit()

    response = await client.get(
        "/api/health/ranking/compare",
        params={"repo_ids": ",".join([row.id for row in public_rows] + [private.id] * 4)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["truncated"] is True
    assert {row["repository_id"] for row in payload["items"]} == {row.id for row in public_rows}
    assert {row["band"] for row in payload["items"]} == {"excellent", "fair"}
    assert payload["score_config_digests"] == ["score"]


@pytest.mark.asyncio
async def test_public_ranking_filters_stale_and_unscored_rows_without_leaking_private_data(
    client, session
) -> None:
    now = datetime.now(UTC)
    fresh = await _publish_ranking_row(
        session,
        name="fresh",
        score=82.5,
        analyzed_at=now,
        stale_after_ts=now + timedelta(days=1),
        now=now,
    )
    stale = await _publish_ranking_row(
        session,
        name="stale",
        score=81,
        analyzed_at=now - timedelta(days=31),
        stale_after_ts=now - timedelta(days=1),
        now=now,
    )
    unscored = await _publish_ranking_row(
        session,
        name="unscored",
        score=None,
        analyzed_at=now,
        stale_after_ts=now + timedelta(days=1),
        now=now,
    )
    thin = await _publish_ranking_row(
        session,
        name="thin-evidence",
        score=83,
        analyzed_at=now,
        stale_after_ts=now + timedelta(days=1),
        now=now,
        evidence_coverage=0.49,
    )
    malformed = await _publish_ranking_row(
        session,
        name="malformed-score",
        score=float("nan"),
        analyzed_at=now,
        stale_after_ts=now + timedelta(days=1),
        now=now,
    )
    private = await _publish_ranking_row(
        session,
        name="private-health",
        score=100,
        analyzed_at=now,
        stale_after_ts=now + timedelta(days=1),
        now=now,
        visibility="private",
    )
    await session.commit()

    default_response = await client.get("/api/health/ranking")
    assert default_response.status_code == 200
    assert [row["repository_id"] for row in default_response.json()["items"]] == [fresh.id]

    all_response = await client.get("/api/health/ranking", params={"include_ineligible": True})
    assert all_response.status_code == 200
    all_payload = all_response.json()
    assert {row["repository_id"] for row in all_payload["items"]} == {
        fresh.id,
        stale.id,
        unscored.id,
        thin.id,
        malformed.id,
    }
    assert private.id not in {row["repository_id"] for row in all_payload["items"]}
    rows_by_id = {row["repository_id"]: row for row in all_payload["items"]}
    assert rows_by_id[stale.id]["stale"] is True
    assert rows_by_id[stale.id]["eligible"] is False
    assert rows_by_id[unscored.id]["overall_score"] is None
    assert rows_by_id[unscored.id]["band"] == "unknown"
    assert rows_by_id[unscored.id]["eligibility_reason"] == "overall score is unavailable"
    assert rows_by_id[thin.id]["eligible"] is False
    assert rows_by_id[thin.id]["eligibility_reason"] == "evidence coverage is below ranking threshold"
    assert rows_by_id[malformed.id]["overall_score"] is None
    assert rows_by_id[malformed.id]["band"] == "unknown"
    assert rows_by_id[malformed.id]["eligibility_reason"] == "overall score is unavailable"
    assert all("local_path" not in row and "raw_payload_ref" not in row for row in all_payload["items"])

    stale_response = await client.get(
        "/api/health/ranking",
        params={"include_ineligible": True, "stale": True},
    )
    assert [row["repository_id"] for row in stale_response.json()["items"]] == [stale.id]

    paged_response = await client.get(
        "/api/health/ranking",
        params={"include_ineligible": True, "page": 2, "limit": 1},
    )
    assert paged_response.status_code == 200
    assert paged_response.json()["total"] == 5
    assert len(paged_response.json()["items"]) == 1

    trend_response = await client.get(
        "/api/health/ranking/trend",
        params={
            "repo_ids": ",".join([fresh.id, stale.id, private.id, unscored.id] * 3),
            "limit": 50,
        },
    )
    assert trend_response.status_code == 200
    assert [series["repository_id"] for series in trend_response.json()["items"]] == [fresh.id]

    for path, params in (
        ("/api/health/ranking", {"page": 0}),
        ("/api/health/ranking", {"limit": 101}),
        ("/api/health/ranking/trend", {"repo_ids": fresh.id, "limit": 0}),
        ("/api/health/ranking/trend", {"repo_ids": fresh.id, "limit": 51}),
    ):
        assert (await client.get(path, params=params)).status_code == 422
    assert (await client.get("/api/health/ranking/compare", params={"repo_ids": ""})).status_code == 422
