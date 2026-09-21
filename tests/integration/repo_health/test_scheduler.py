"""Minimal scheduler overlap and shutdown gates."""

from __future__ import annotations

import asyncio

from repo_health.infrastructure.scheduler import IntervalScheduler


async def test_interval_scheduler_prevents_overlap_and_reports_jobs() -> None:
    scheduler = IntervalScheduler()
    active = 0
    maximum = 0

    async def callback() -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02)
        active -= 1

    scheduler.add_interval(callback, seconds=0.005, name="fixture")
    await asyncio.sleep(0.07)
    assert maximum == 1
    assert scheduler.status()["jobs"]
    await scheduler.shutdown()
    assert scheduler.status()["stopping"] is True
