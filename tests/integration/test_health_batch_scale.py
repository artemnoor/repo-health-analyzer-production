import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
)
from repowise.core.analysis.health.integrations.orchestrator import HealthOrchestrator
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry


@pytest.mark.asyncio
async def test_batch_scale_keeps_analyzer_work_bounded_and_isolates_repositories() -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return AnalyzerResult(
            analyzer_id="fixture.batch",
            analyzer_version="1",
            status=AnalyzerStatus.PASS,
            score=90,
            score_dimension="code",
            available_weight=1,
            total_weight=1,
        )

    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(
            id="fixture.batch",
            version="1",
            category="calibration",
            requires=("local_scan",),
            cache_policy="none",
        ),
        factory,
    )
    contexts = [
        AnalyzerContext(
            repo_path=Path("."),
            repo_id=f"repo-{index}",
            head_sha="head",
            as_of_ts=datetime(2026, 9, 11, tzinfo=UTC),
            capabilities=("local_scan",),
        )
        for index in range(12)
    ]

    batch = await HealthOrchestrator(
        analyzer_registry=registry,
        max_concurrency=3,
        max_retries=0,
    ).run_batch(contexts)

    assert batch.completed == 12
    assert batch.failed == 0
    assert max_active <= 3
    assert max_active > 1
