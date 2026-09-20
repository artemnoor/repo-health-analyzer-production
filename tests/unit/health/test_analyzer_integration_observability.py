"""Focused structured-observability contract tests for analyzer integration."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from repowise.core.analysis.analyzer_integration.cache import FileAnalyzerCache
from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    Limitation,
)
from repowise.core.analysis.analyzer_integration.lifecycle import LifecycleOrchestrator
from repowise.core.analysis.analyzer_integration.process import ProcessRequest, SubprocessProcess
from repowise.core.analysis.analyzer_integration.registry import AnalyzerRegistry
from repowise.core.analysis.analyzer_integration.runner import AnalyzerRunner


def _context(tmp_path: Path) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=tmp_path,
        repo_id="observability-repo",
        head_sha="head",
        as_of_ts=datetime(2026, 9, 14, tzinfo=UTC),
        cache_dir=tmp_path / "cache",
    )


def _result(
    analyzer_id: str = "fixture", *, status: AnalyzerStatus = AnalyzerStatus.PASS
) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="1",
        status=status,
        limitations=(Limitation(reason="fixture error", kind="error"),)
        if status is AnalyzerStatus.ERROR
        else (),
    )


def _assert_common_fields(event: dict[str, object]) -> None:
    assert {
        "run_key",
        "repository_id",
        "phase",
        "completed_phases",
        "status",
        "duration_ms",
    } <= event.keys()


def test_cache_events_report_outcomes_without_result_payloads(tmp_path: Path) -> None:
    cache = FileAnalyzerCache(tmp_path)
    with capture_logs() as events:
        assert cache.get("missing", analyzer_id="fixture", analyzer_version="1") is None
        cache.put("present", _result(), analyzer_id="fixture")
        assert cache.get("present", analyzer_id="fixture", analyzer_version="1") is not None
        cache.put("error", _result(status=AnalyzerStatus.ERROR), analyzer_id="fixture")

    names = [event["event"] for event in events]
    assert {"cache_miss", "cache_write", "cache_hit", "cache_write_skipped"} <= set(names)
    for event in events:
        if event["event"] in {"cache_miss", "cache_write", "cache_hit", "cache_write_skipped"}:
            assert {
                "cache_key",
                "cache_path",
                "analyzer_id",
                "analyzer_version",
                "run_key",
                "repository_id",
                "phase",
                "completed_phases",
                "status",
                "duration_ms",
                "failure_kind",
            } <= event.keys()
            assert "result" not in event and "payload" not in event


def test_process_events_report_bounded_outcome_without_command_values(tmp_path: Path) -> None:
    with capture_logs() as events:
        output = SubprocessProcess().run(
            ProcessRequest(
                tool_id="observability-process",
                executable=sys.executable,
                args=("-c", "print('bounded')"),
                cwd=tmp_path,
                output_cap=128,
            )
        )

    assert output.exit_code == 0
    for event in events:
        if event["event"] in {"process_started", "process_finished"}:
            assert {
                "tool_id",
                "run_key",
                "repository_id",
                "phase",
                "completed_phases",
                "status",
                "exit_code",
                "duration_ms",
                "timed_out",
                "truncated",
            } <= event.keys()
            assert not {"executable", "args", "environment", "stdout", "stderr"} & event.keys()


def test_runner_events_include_correlation_and_terminal_failure_metadata(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    definition = AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none")
    registry.register(definition, lambda context: _result())

    with capture_logs() as events:
        result = AnalyzerRunner().run(registry.plan(_context(tmp_path))[0], _context(tmp_path))

    assert result.status is AnalyzerStatus.PASS
    started = next(event for event in events if event["event"] == "analyzer_started")
    finished = next(event for event in events if event["event"] == "analyzer_finished")
    required = {
        "analyzer_id",
        "analyzer_version",
        "run_key",
        "repository_id",
        "status",
        "duration_ms",
        "cache_hit",
        "timeout",
        "failure_kind",
    }
    assert required <= started.keys()
    assert required <= finished.keys()


@pytest.mark.asyncio
async def test_lifecycle_and_runner_share_the_repository_correlation_key(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        lambda context: _result(),
    )

    with capture_logs() as events:
        outcome = await LifecycleOrchestrator(analyzer_registry=registry).run_repository(
            _context(tmp_path)
        )

    assert outcome.status == "completed"
    lifecycle = next(event for event in events if event["event"] == "lifecycle_started")
    analyzer = next(event for event in events if event["event"] == "analyzer_started")
    assert lifecycle["run_key"] == analyzer["run_key"]
    assert analyzer["repository_id"] == "observability-repo"


def test_runner_failure_logs_redact_exception_messages(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        raise RuntimeError("password=super-secret token=abc123")

    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        factory,
    )
    with capture_logs() as events:
        result = AnalyzerRunner().run(registry.plan(_context(tmp_path))[0], _context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    rendered = repr(events)
    assert "super-secret" not in rendered
    assert "abc123" not in rendered
    detail = next(event for event in events if event["event"] == "analyzer_failure_detail")
    assert detail["error_message"] == "RuntimeError (message redacted)"


@pytest.mark.asyncio
async def test_lifecycle_events_cover_phases_checkpoints_and_retries(tmp_path: Path) -> None:
    class Checkpoint:
        async def begin(self, **kwargs: object) -> object:
            return type("State", (), {"job_id": "observability-job"})()

        async def checkpoint(self, state: object, **kwargs: object) -> None:
            return None

        async def complete(self, state: object, **kwargs: object) -> None:
            return None

        async def fail(self, state: object, **kwargs: object) -> None:
            return None

    attempts = 0

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        nonlocal attempts
        attempts += 1
        return _result(status=AnalyzerStatus.ERROR) if attempts == 1 else _result()

    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        factory,
    )
    with capture_logs() as events:
        outcome = await LifecycleOrchestrator(
            analyzer_registry=registry,
            checkpoint=Checkpoint(),
            max_retries=1,
        ).run_repository(_context(tmp_path))

    assert outcome.status == "completed"
    assert attempts == 2
    assert {
        "phase_started",
        "phase_finished",
        "checkpoint",
        "analyzer_retry",
        "lifecycle_finished",
    } <= {event["event"] for event in events}
    for event in events:
        if event["event"] in {
            "phase_started",
            "phase_finished",
            "checkpoint",
            "analyzer_retry",
            "lifecycle_finished",
        }:
            _assert_common_fields(event)


def test_health_bootstrap_emits_one_sorted_registration_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repowise.core.analysis.health.integrations import register_all_health_adapters

    registry = AnalyzerRegistry()
    with capture_logs() as events:
        registered = register_all_health_adapters(registry)

    summaries = [event for event in events if event["event"] == "health_bootstrap_completed"]
    assert len(summaries) == 1
    assert not [event for event in events if event["event"] == "analyzer_registered"]
    summary = summaries[0]
    assert summary["status"] == "completed"
    assert summary["analyzer_ids"] == tuple(sorted(registered.ids()))
    assert summary["analyzer_count"] == len(registered.ids())
    assert summary["idempotent"] is False
