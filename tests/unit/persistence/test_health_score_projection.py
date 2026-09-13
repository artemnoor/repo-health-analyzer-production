from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    MetricValue,
)
from repowise.core.persistence.crud import save_health_envelope
from repowise.core.persistence.models import HealthScoreProjection
from tests.unit.persistence.helpers import insert_repo


async def test_save_writes_one_composite_score_projection(async_session) -> None:
    repo = await insert_repo(async_session)
    as_of = datetime(2026, 9, 10, tzinfo=UTC)
    ref = EvidenceRef(source="fixture", source_commit="head", collected_at=as_of)
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id=repo.id,
        head_sha="a" * 40,
        as_of_ts=as_of,
        capabilities=["local_scan"],
    )
    result = AnalyzerResult(
        analyzer_id="fixture.code",
        analyzer_version="1",
        status=AnalyzerStatus.PASS,
        metrics=(MetricValue(name="code:quality", dimension="code", score=82, denominator=1, evidence_refs=(ref,)),),
        evidence=(ref,),
        available_weight=1,
        total_weight=1,
    )

    snapshot = await save_health_envelope(async_session, repo.id, context, [result])
    await async_session.commit()
    projection = (
        await async_session.execute(select(HealthScoreProjection).where(HealthScoreProjection.snapshot_id == snapshot.id))
    ).scalar_one()

    assert projection.overall_score == 82
    assert projection.score_config_digest == snapshot.score_config_digest
    assert '"code":82.0' in projection.dimensions_json
