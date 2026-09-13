import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    MetricValue,
)
from repowise.core.persistence.crud import rescore_health_snapshot, save_health_envelope
from repowise.core.persistence.database import init_db
from repowise.core.persistence.models import (
    HealthRawFact,
    HealthRecommendation,
    HealthScoreProjection,
    RepositoryHealthSnapshot,
)
from repowise.server.routers.code_health.canonical_routes import canonical_health
from tests.unit.persistence.helpers import insert_repo


@pytest.fixture
async def async_session(tmp_path: Path):
    db_path = tmp_path / "health.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.info["session_factory"] = factory
        session.info["db_url"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        yield session
    await engine.dispose()


async def test_rescore_reuses_stored_metrics_and_marks_projection_recomputed(async_session) -> None:
    repo = await insert_repo(async_session, name="rescore-health")
    as_of = datetime(2026, 9, 10, tzinfo=UTC)
    ref = EvidenceRef(source="fixture", collected_at=as_of)
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id=repo.id,
        head_sha="a" * 40,
        as_of_ts=as_of,
        capabilities=["local_scan"],
        inventory={"raw_facts": [{"source": "fixture", "event_type": "commit", "stable_event_id": "c1", "payload": {}}]},
    )
    result = AnalyzerResult(
        analyzer_id="fixture.code",
        analyzer_version="1",
        status=AnalyzerStatus.PASS,
        metrics=(MetricValue(name="code:quality", dimension="code", score=80, denominator=1, evidence_refs=(ref,)),),
        evidence=(ref,),
        available_weight=1,
        total_weight=1,
    )
    snapshot = await save_health_envelope(async_session, repo.id, context, [result])
    await async_session.commit()
    raw_before = len((await async_session.execute(select(HealthRawFact))).scalars().all())

    await rescore_health_snapshot(async_session, snapshot.id, {"weights": {"code": 1}}, score_config_digest="rescored")
    await async_session.commit()
    projection = (
        await async_session.execute(
            select(HealthScoreProjection).where(
                HealthScoreProjection.snapshot_id == snapshot.id,
                HealthScoreProjection.score_config_digest == "rescored",
            )
        )
    ).scalar_one()

    assert projection.overall_score == 80
    assert projection.score_recomputed is True
    assert len((await async_session.execute(select(HealthRawFact))).scalars().all()) == raw_before


def _without_volatile_fields(value):
    """Keep parity assertions strict while excluding runtime timing fields only."""
    volatile = {"duration_ms", "generated_at"}
    if isinstance(value, dict):
        return {
            key: _without_volatile_fields(item)
            for key, item in value.items()
            if key not in volatile
        }
    if isinstance(value, list):
        return [_without_volatile_fields(item) for item in value]
    return value


@pytest.mark.asyncio
async def test_canonical_projection_is_identical_across_rest_mcp_and_cli(
    async_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All inbound adapters must expose the persisted projection unchanged."""
    repo_path = tmp_path / "repository"
    repo = await insert_repo(async_session, name="parity-health", local_path=str(repo_path))
    as_of = datetime(2026, 9, 10, 12, tzinfo=UTC)
    snapshot = RepositoryHealthSnapshot(
        repository_id=repo.id,
        head_sha="c" * 40,
        analyzed_at=as_of,
        as_of_ts=as_of,
        config_digest="config-parity",
        analyzer_versions_digest="analyzers-parity",
        score_config_digest="score-parity",
        scope="all",
        mode="full",
        status="warn",
        score=9.1,
        confidence=0.88,
        evidence_coverage=0.8,
        criticality=0.4,
        diagnostics_json=json.dumps({"source_order": "raw-normalized-derived"}),
    )
    async_session.add(snapshot)
    await async_session.flush()
    async_session.add(
        HealthScoreProjection(
            snapshot_id=snapshot.id,
            score_config_digest="score-parity",
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
        )
    )
    async_session.add(
        HealthRecommendation(
            snapshot_id=snapshot.id,
            recommendation_id="rec-parity",
            finding_id="finding-parity",
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
    await async_session.commit()

    rest = await canonical_health(
        repo.id,
        snapshot=None,
        scope="all",
        dimension=None,
        status=None,
        severity=None,
        subject=None,
        window=None,
        include_evidence=True,
        session=async_session,
    )

    import repowise.server.mcp_server as mcp_mod

    mcp_mod._session_factory = async_session.info["session_factory"]
    mcp_mod._repo_path = str(repo_path)
    mcp_mod._fts = None
    mcp_mod._vector_store = None
    mcp_mod._decision_store = None
    mcp_mod._registry = None
    try:
        from repowise.server.mcp_server import get_health

        mcp = await get_health(
            include=["canonical"],
            only=["canonical"],
            snapshot_id=None,
            scope="all",
            include_evidence=True,
        )
    finally:
        mcp_mod._session_factory = None
        mcp_mod._repo_path = None
        mcp_mod._fts = None
        mcp_mod._vector_store = None
        mcp_mod._decision_store = None
        mcp_mod._registry = None

    monkeypatch.setenv("REPOWISE_DB_URL", async_session.info["db_url"])
    from repowise.cli.commands.health_cmd.persist import _load_canonical_health

    cli = await asyncio.to_thread(
        _load_canonical_health,
        repo_path,
        scope="all",
        include_evidence=True,
    )

    assert cli is not None
    assert rest["score_projection"]["overall_score"] == 82.5
    assert mcp["canonical"]["score_projection"]["overall_score"] == 82.5
    assert cli["score_projection"]["score_config_digest"] == "score-parity"
    assert mcp["canonical"]["recommendations"][0]["remediation"] == (
        "Run the security analyzer."
    )
    assert _without_volatile_fields(rest) == _without_volatile_fields(mcp["canonical"])
    assert _without_volatile_fields(rest) == _without_volatile_fields(cli)
