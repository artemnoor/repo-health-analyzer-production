from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from repowise.core.persistence.database import init_db
from repowise.core.repo_health.contracts import (
    AnalysisEnvelope,
    AnalysisRequest,
    AnalysisState,
    AnalysisStatus,
    RepositoryFacts,
    RepositoryRef,
)
from repowise.core.repo_health.persistence import (
    AnalysisEnvelopeConflictError,
    SqlAnalysisEnvelopeStore,
)
from tests.unit.persistence.helpers import insert_repo


@pytest.fixture
async def async_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'repo-health.db'}")
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def _envelope(*, repository_id: str, analysis_id: str | None = None) -> AnalysisEnvelope:
    as_of = datetime(2026, 9, 20, 12, tzinfo=UTC)
    repository = RepositoryRef(
        repository_id=repository_id,
        canonical_uri="https://example.test/acme/repo",
        provider="github",
        ref="main",
        head_sha="a" * 40,
    )
    request = AnalysisRequest(
        analysis_id=analysis_id,
        repository=repository,
        as_of=as_of,
        idempotency_key="run-1",
    )
    status = AnalysisStatus(analysis_id=request.analysis_id, state=AnalysisState.QUEUED)
    return AnalysisEnvelope(
        analysis_id=request.analysis_id,
        request=request,
        facts=RepositoryFacts(repository=repository),
        status=status,
        idempotency_key="run-1",
        created_at=as_of,
    )


async def test_sql_envelope_round_trip_and_idempotent_replay(async_session) -> None:
    repo = await insert_repo(async_session)
    envelope = _envelope(repository_id=repo.id)
    store = SqlAnalysisEnvelopeStore(async_session)

    first = await store.write(envelope)
    repeated = await store.write(envelope)
    await async_session.commit()

    assert repeated == first == envelope
    assert await store.get(envelope.analysis_id) == envelope
    assert await store.get_by_idempotency(repo.id, "run-1") == envelope


async def test_sql_envelope_rejects_idempotency_reuse_with_different_content(async_session) -> None:
    repo = await insert_repo(async_session)
    store = SqlAnalysisEnvelopeStore(async_session)
    await store.write(_envelope(repository_id=repo.id, analysis_id="analysis-one"))

    with pytest.raises(AnalysisEnvelopeConflictError):
        await store.write(_envelope(repository_id=repo.id, analysis_id="analysis-two"))
