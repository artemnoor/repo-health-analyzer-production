from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from repowise.core.persistence.database import init_db
from repowise.core.repo_health.execution import QueueConflictError, SqlQueue
from tests.contract.repo_health.test_execution_contracts import _task


@pytest.fixture
async def async_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue.db'}")
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_sql_queue_claim_ack_and_idempotency(async_session) -> None:
    queue = SqlQueue(async_session)
    task = _task()
    await queue.publish(task)
    await queue.publish(task)
    await async_session.commit()

    lease = await queue.claim("worker-1")
    assert lease is not None
    assert lease.task.task_id == task.task_id
    await queue.ack(task.task_id, "worker-1")
    await async_session.commit()
    assert await queue.claim("worker-2") is None


async def test_sql_queue_rejects_conflicting_idempotency(async_session) -> None:
    queue = SqlQueue(async_session)
    await queue.publish(_task())
    conflicting = _task().model_copy(update={"analysis_id": "analysis-2"})

    with pytest.raises(QueueConflictError):
        await queue.publish(conflicting)
