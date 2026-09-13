from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
)
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry


def _context(*capabilities: str, languages: list[str] | None = None) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id="demo",
        head_sha="abc",
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=capabilities,
        inventory={"languages": languages or []},
    )


def _factory(analyzer_id: str):
    def run(context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            analyzer_id=analyzer_id,
            analyzer_version="1",
            status=AnalyzerStatus.PASS,
            score=100,
            available_weight=1,
            total_weight=1,
        )

    return run


def test_duplicate_ids_are_rejected_before_execution() -> None:
    registry = AnalyzerRegistry()
    definition = AnalyzerDefinition(id="same", version="1", category="test")
    registry.register(definition, _factory("same"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(definition, _factory("same"))


def test_plan_order_is_phase_then_cost_then_id() -> None:
    registry = AnalyzerRegistry()
    for analyzer_id, phase, cost in [("z", 2, 1), ("b", 1, 20), ("a", 1, 20), ("c", 1, 5)]:
        registry.register(
            AnalyzerDefinition(id=analyzer_id, version="1", category="test", phase=phase, cost=cost),
            _factory(analyzer_id),
        )

    assert [item.definition.id for item in registry.plan(_context())] == ["c", "a", "b", "z"]


def test_missing_capability_becomes_skipped_without_calling_factory() -> None:
    registry = AnalyzerRegistry()
    called = False

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        nonlocal called
        called = True
        raise AssertionError("must not run")

    registry.register(
        AnalyzerDefinition(id="security", version="1", category="security", requires=["security_db"]),
        factory,
    )
    planned = registry.plan(_context("git"))[0]
    result = registry.run(planned, _context("git"))

    assert planned.ready is False
    assert result.status is AnalyzerStatus.SKIPPED
    assert result.score is None
    assert called is False


def test_unsupported_language_and_experimental_analyzer_are_planned_as_skipped() -> None:
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="java", version="1", category="quality", supports=["java"]),
        _factory("java"),
    )
    registry.register(
        AnalyzerDefinition(id="experimental", version="1", category="quality", experimental=True),
        _factory("experimental"),
    )

    planned = registry.plan(_context(languages=["python"]))

    by_id = {item.definition.id: item for item in planned}
    assert by_id["java"].missing_capabilities == ("unsupported:java",)
    assert by_id["experimental"].disabled_reason == "experimental analyzer is disabled"


def test_runner_isolates_invalid_factory_output() -> None:
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="broken", version="1", category="test", cache_policy="none"),
        lambda context: {"not": "an analyzer result"},  # type: ignore[return-value]
    )

    result = registry.run(registry.plan(_context())[0], _context())

    assert result.status is AnalyzerStatus.ERROR
    assert result.score is None
    assert result.limitations[0].kind == "error"
