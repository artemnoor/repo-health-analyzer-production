import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    MetricValue,
)
from repowise.core.persistence.crud import (
    load_health_snapshot_envelope,
    rescore_health_snapshot,
    save_health_envelope,
)
from repowise.core.persistence.models import (
    HealthAggregate,
    HealthFindingEvidence,
    HealthMetricValue,
    HealthNormalizedFact,
    HealthRawFact,
    HealthRecommendation,
    HealthSourceRun,
    RepositoryHealthSnapshot,
)
from tests.unit.persistence.helpers import insert_repo


def _context(
    repo_id: str,
    *,
    raw_facts: list[dict],
    as_of: datetime | None = None,
    head_sha: str | None = None,
    stale_after: int | None = None,
) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id=repo_id,
        head_sha=head_sha or "d" * 40,
        as_of_ts=as_of or datetime(2026, 9, 10, tzinfo=UTC),
        scope="all",
        mode="full",
        capabilities=["chaoss:events"],
        inventory={
            "raw_facts": raw_facts,
            "criticality": 0.7,
            **({"stale_after": stale_after} if stale_after is not None else {}),
        },
    )


def _results(as_of: datetime) -> tuple[AnalyzerResult, ...]:
    evidence = EvidenceRef(source="fixture", source_commit="source-1", path="src/app.py", collected_at=as_of)
    return (
        AnalyzerResult(
            analyzer_id="repowise.health",
            analyzer_version="10",
            status=AnalyzerStatus.PASS,
            score=72.0,
            metrics=(
                MetricValue(name="quality:structure", value=8, unit="score", score=80, denominator=1, evidence_refs=(evidence,)),
                MetricValue(name="quality:history", value=6, unit="score", score=60, denominator=1, evidence_refs=(evidence,)),
            ),
            evidence=(evidence,),
            source_versions={"repowise": "10"},
            available_weight=2,
            total_weight=2,
        ),
        AnalyzerResult(
            analyzer_id="fixture.security",
            analyzer_version="1",
            status=AnalyzerStatus.WARN,
            metrics=(MetricValue(name="security:policy", value=True, unit="present", denominator=1, evidence_refs=(evidence,)),),
            findings=(
                Finding(
                    id="finding-1",
                    analyzer_id="fixture.security",
                    subject="src/app.py",
                    dimension="security",
                    severity="high",
                    confidence=0.9,
                    reason="Security policy evidence is incomplete.",
                    evidence_refs=(evidence,),
                    location=FindingLocation(path="src/app.py", line_start=3, line_end=4),
                    raw_impact=3,
                    applied_impact=3,
                ),
            ),
            evidence=(evidence,),
            source_versions={"fixture": "1"},
            available_weight=1,
            total_weight=1,
        ),
    )


async def test_envelope_writes_raw_before_derived_and_round_trips(async_session) -> None:
    repo_id = (await insert_repo(async_session)).id
    context = _context(repo_id, raw_facts=[{"source": "perceval", "event_type": "commit", "stable_event_id": "c1", "updated_at": "2026-09-09T12:00:00+03:00", "payload": {"author": {"email": "redacted@example.com"}}}])
    results = _results(context.as_of_ts)

    snapshot = await save_health_envelope(async_session, repo_id, context, results)
    await async_session.commit()
    repeated = await save_health_envelope(async_session, repo_id, context, results)

    assert repeated.id == snapshot.id
    assert (await async_session.execute(select(HealthSourceRun).where(HealthSourceRun.snapshot_id == snapshot.id))).scalars().all()
    assert (await async_session.execute(select(HealthRawFact).where(HealthRawFact.snapshot_id == snapshot.id))).scalars().all()
    assert (await async_session.execute(select(HealthNormalizedFact).where(HealthNormalizedFact.snapshot_id == snapshot.id))).scalars().all()
    assert (await async_session.execute(select(HealthMetricValue).where(HealthMetricValue.snapshot_id == snapshot.id))).scalars().all()
    assert (await async_session.execute(select(HealthFindingEvidence).where(HealthFindingEvidence.snapshot_id == snapshot.id))).scalars().all()
    assert (await async_session.execute(select(HealthAggregate).where(HealthAggregate.snapshot_id == snapshot.id))).scalars().all()
    assert (await async_session.execute(select(HealthRecommendation).where(HealthRecommendation.snapshot_id == snapshot.id))).scalars().all()
    projection = await load_health_snapshot_envelope(async_session, snapshot.id)
    assert projection is not None
    assert projection["snapshot"]["score"] == 72.0
    assert projection["snapshot"]["criticality"] == 0.7
    assert projection["recommendations"][0]["finding_status"] == "open"
    assert projection["recommendations"][0]["severity"] == "high"
    assert json.loads(projection["recommendations"][0]["location_json"])["path"] == "src/app.py"
    assert {row["name"] for row in projection["metrics"]} == {"quality:history", "quality:structure", "security:policy"}


async def test_rescore_uses_stored_metric_values_without_new_source_rows(async_session) -> None:
    repo_id = (await insert_repo(async_session)).id
    context = _context(repo_id, raw_facts=[])
    snapshot = await save_health_envelope(async_session, repo_id, context, _results(context.as_of_ts))
    await async_session.commit()

    before_raw = (await async_session.execute(select(HealthRawFact))).scalars().all()
    first = await rescore_health_snapshot(async_session, snapshot.id, {"weights": {"quality:structure": 1, "quality:history": 3}}, score_config_digest="score-a")
    second = await rescore_health_snapshot(async_session, snapshot.id, {"weights": {"quality:structure": 3, "quality:history": 1}}, score_config_digest="score-b")
    await async_session.commit()
    after_raw = (await async_session.execute(select(HealthRawFact))).scalars().all()

    assert len(first) == 1
    assert len(second) == 1
    assert round(float(first[0].score or 0), 2) == 65.0
    assert round(float(second[0].score or 0), 2) == 75.0
    assert len(after_raw) == len(before_raw)
    assert (await async_session.execute(select(HealthAggregate).where(HealthAggregate.snapshot_id == snapshot.id))).scalars().all()


async def test_envelope_rollback_leaves_no_partial_source_or_derived_rows(async_session) -> None:
    repo_id = (await insert_repo(async_session)).id
    context = _context(repo_id, raw_facts=[{"source": "fixture", "event_type": "commit", "stable_event_id": "rollback", "payload": {}}])
    snapshot = await save_health_envelope(async_session, repo_id, context, _results(context.as_of_ts))
    await async_session.rollback()

    assert (await async_session.execute(select(RepositoryHealthSnapshot).where(RepositoryHealthSnapshot.id == snapshot.id))).scalar_one_or_none() is None
    assert (await async_session.execute(select(HealthRawFact))).scalars().all() == []


async def test_snapshot_comparison_reports_delta_and_staleness_without_rescoring(async_session) -> None:
    repo_id = (await insert_repo(async_session)).id
    previous_context = _context(
        repo_id,
        raw_facts=[],
        as_of=datetime(2026, 9, 9, tzinfo=UTC),
        head_sha="a" * 40,
    )
    current_context = _context(
        repo_id,
        raw_facts=[],
        as_of=datetime(2026, 9, 10, tzinfo=UTC),
        head_sha="b" * 40,
        stale_after=-1,
    )
    previous = await save_health_envelope(
        async_session, repo_id, previous_context, _results(previous_context.as_of_ts)
    )
    current = await save_health_envelope(
        async_session, repo_id, current_context, _results(current_context.as_of_ts)
    )
    await async_session.commit()

    from repowise.core.persistence.crud import compare_health_snapshots

    comparison = await compare_health_snapshots(async_session, current.id, previous.id)

    assert comparison["previous_snapshot_id"] == previous.id
    assert comparison["score_delta"] == 0.0
    assert comparison["is_stale"] is True
    assert comparison["decline_attribution"] == "none"
    assert set(comparison["dimensions"]) == {"fixture", "repowise"}
