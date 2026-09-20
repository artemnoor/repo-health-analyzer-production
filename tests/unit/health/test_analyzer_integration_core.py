"""Acceptance coverage for the neutral analyzer integration kernel."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.analyzer_integration.cache import cache_key
from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    MetricValue,
)
from repowise.core.analysis.analyzer_integration.finding_merge import deduplicate_findings
from repowise.core.analysis.analyzer_integration.lifecycle import LifecycleOrchestrator, run_key
from repowise.core.analysis.analyzer_integration.process import ProcessRequest, SubprocessProcess
from repowise.core.analysis.analyzer_integration.registry import AnalyzerRegistry
from repowise.core.analysis.analyzer_integration.runner import AnalyzerRunner


def _context(tmp_path: Path, *, repo_id: str = "repo") -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=tmp_path,
        repo_id=repo_id,
        head_sha="head",
        as_of_ts=datetime(2026, 9, 13, tzinfo=UTC),
        capabilities=("scan",),
        cache_dir=tmp_path / "cache",
    )


def _definition(analyzer_id: str = "fixture", **kwargs) -> AnalyzerDefinition:
    return AnalyzerDefinition(
        id=analyzer_id, version="1", category="test", **{"cache_policy": "none", **kwargs}
    )


def _result(
    analyzer_id: str = "fixture", *, status: AnalyzerStatus = AnalyzerStatus.PASS
) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=analyzer_id,
        analyzer_version="1",
        status=status,
        score=90 if status is AnalyzerStatus.PASS else None,
        metrics=(MetricValue(name="score", dimension="code", score=90, denominator=1),),
        available_weight=1 if status is AnalyzerStatus.PASS else 0,
        total_weight=1,
    )


def test_contract_golden_round_trip_preserves_all_result_fields() -> None:
    collected = datetime(2026, 9, 13, 12, 30, tzinfo=UTC)
    evidence = EvidenceRef(
        source="fixture", collected_at=collected, path="src/app.py", line_start=4, line_end=7
    )
    result = AnalyzerResult(
        analyzer_id="fixture",
        analyzer_version="1",
        status=AnalyzerStatus.WARN,
        score=74.5,
        score_dimension="code",
        metrics=(
            MetricValue(
                name="quality",
                dimension="code",
                value=4,
                score=74.5,
                denominator=10,
                evidence_refs=(evidence,),
            ),
        ),
        findings=(
            Finding(
                id="finding-1",
                analyzer_id="fixture",
                subject="src/app.py",
                dimension="code",
                severity="high",
                confidence=0.8,
                reason="complexity",
                evidence_refs=(evidence,),
                location=FindingLocation(path="src/app.py", line_start=4, line_end=7),
                remediation="split it",
                raw_impact=3,
                applied_impact=2,
            ),
        ),
        evidence=(evidence,),
        limitations=(
            Limitation(reason="partial fixture", kind="other", evidence_refs=(evidence,)),
        ),
        duration_ms=12,
        cache_hit=True,
        source_versions={"tool": "v1"},
        available_weight=3,
        total_weight=4,
        raw_payload_ref="fixture://result",
        diagnostics={"source": "golden", "order": ["a", "b"]},
    )
    restored = AnalyzerResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.model_dump_json() == result.model_dump_json()
    assert {status.value for status in AnalyzerStatus} == {
        "pass",
        "warn",
        "fail",
        "skipped",
        "inconclusive",
        "error",
    }


def test_registry_is_empty_and_fake_registry_is_deterministic(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    assert registry.ids() == ()
    registry.register(_definition("z", phase=2, cost=1), lambda context: _result("z"))
    registry.register(_definition("a", phase=1, cost=1), lambda context: _result("a"))
    assert [item.definition.id for item in registry.plan(_context(tmp_path))] == ["a", "z"]


def test_registry_gates_preserve_absent_language_inventory_semantics(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    registry.register(
        _definition("language", supports=("python",), enabled_by_mode=("full",)),
        lambda context: _result("language"),
    )
    absent = _context(tmp_path).model_copy(update={"mode": "full", "inventory": {}})
    unsupported = absent.model_copy(update={"inventory": {"languages": ["go"]}})
    disabled = _context(tmp_path).model_copy(update={"mode": "fast"})
    assert registry.plan(absent)[0].ready is True
    assert registry.plan(unsupported)[0].missing_capabilities == ("unsupported:python",)
    assert registry.plan(disabled)[0].disabled_reason == "analyzer is disabled for mode fast"


def test_runner_converts_identity_failure_and_does_not_cache_error(tmp_path: Path) -> None:
    definition = _definition("expected")
    registry = AnalyzerRegistry()
    registry.register(definition, lambda context: _result("wrong"))
    context = _context(tmp_path)
    result = AnalyzerRunner().run(registry.plan(context)[0], context)
    assert result.status is AnalyzerStatus.ERROR
    assert result.limitations[0].kind == "error"
    assert (
        not list((context.cache_dir / "health-analyzers").glob("*"))
        if context.cache_dir.exists()
        else True
    )


@pytest.mark.parametrize("error", (ValueError("bad result"), TypeError("bad result")))
def test_runner_preserves_legacy_factory_exception_payload(
    tmp_path: Path, error: Exception
) -> None:
    registry = AnalyzerRegistry()

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        raise error

    registry.register(_definition("factory-error"), factory)
    result = AnalyzerRunner().run(registry.plan(_context(tmp_path))[0], _context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert result.limitations[0].reason == f"invalid analyzer result: {type(error).__name__}"
    assert result.limitations[0].kind == "error"
    assert result.diagnostics == {}


def test_runner_timeout_returns_error_and_sibling_can_run(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    registry.register(
        _definition("slow", timeout=0.02), lambda context: (time.sleep(0.15), _result("slow"))[1]
    )
    registry.register(_definition("fast"), lambda context: _result("fast"))
    context = _context(tmp_path)
    runner = AnalyzerRunner()
    planned = {item.definition.id: item for item in registry.plan(context)}
    timed_out = runner.run(planned["slow"], context)
    assert timed_out.status is AnalyzerStatus.ERROR
    assert timed_out.limitations[0].kind == "timeout"
    assert runner.run(planned["fast"], context).status is AnalyzerStatus.PASS


def test_cache_hit_corruption_and_policy(tmp_path: Path) -> None:
    definition = _definition("cached", cache_policy="read_write")
    context = _context(tmp_path)
    registry = AnalyzerRegistry()
    calls = 0

    def factory(ctx):
        nonlocal calls
        calls += 1
        return _result("cached")

    registry.register(definition, factory)
    planned = registry.plan(context)[0]
    runner = AnalyzerRunner()
    assert runner.run(planned, context).cache_hit is False
    assert runner.run(planned, context).cache_hit is True
    assert calls == 1
    path = next((context.cache_dir / "health-analyzers").glob("cached-*.json"))
    assert not list((context.cache_dir / "health-analyzers").glob("*.tmp"))
    path.write_text("not-json", encoding="utf-8")
    assert runner.run(planned, context).cache_hit is False
    assert calls == 2
    assert cache_key(planned, context) == cache_key(planned, context)


def test_injected_cache_hit_is_marked_as_a_cache_hit(tmp_path: Path) -> None:
    class Cache:
        def get(self, key: str) -> AnalyzerResult:
            return _result("cached")

        def put(self, key: str, result: AnalyzerResult) -> None:
            raise AssertionError("a read-only cache must not be written")

    registry = AnalyzerRegistry()
    calls = 0

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        nonlocal calls
        calls += 1
        return _result("cached")

    registry.register(_definition("cached", cache_policy="read"), factory)
    context = _context(tmp_path)
    result = AnalyzerRunner(cache=Cache()).run(registry.plan(context)[0], context)
    assert result.cache_hit is True
    assert calls == 0


def test_cache_path_components_cannot_escape_root(tmp_path: Path) -> None:
    from repowise.core.analysis.analyzer_integration.cache import FileAnalyzerCache

    cache = FileAnalyzerCache(tmp_path)
    for kwargs in (
        {"key": "../outside"},
        {"key": "safe", "analyzer_id": "../outside"},
    ):
        with pytest.raises(ValueError):
            cache.path_for(**kwargs)
    with pytest.raises(ValueError):
        FileAnalyzerCache(tmp_path, namespace="../outside")


def test_process_is_shell_free_allowlisted_and_bounded(tmp_path: Path) -> None:
    process = SubprocessProcess()
    success = process.run(
        ProcessRequest(
            tool_id="echo",
            executable=sys.executable,
            args=(
                "-c",
                "import os,sys; print(os.getenv('SECRET','missing')); print(sys.stdin.read())",
            ),
            cwd=tmp_path,
            environment={"PATH": os.environ.get("PATH", ""), "SECRET": "hidden"},
            stdin="input",
        )
    )
    assert success.exit_code == 0
    assert "missing" in success.stdout and "input" in success.stdout
    cwd_result = process.run(
        ProcessRequest(
            tool_id="cwd",
            executable=sys.executable,
            args=("-c", "import os; print(os.getcwd())"),
            cwd=tmp_path,
        )
    )
    # The allowlisted child environment intentionally omits locale overrides;
    # compare the stable ASCII tail instead of relying on Windows code pages.
    assert cwd_result.stdout.strip().endswith(str(tmp_path.name))
    failed = process.run(
        ProcessRequest(
            tool_id="failed",
            executable=sys.executable,
            args=("-c", "raise SystemExit(3)"),
        )
    )
    assert failed.exit_code == 3
    bounded = process.run(
        ProcessRequest(
            tool_id="bounded",
            executable=sys.executable,
            args=("-c", "import sys; print('x' * 1000); sys.stderr.write('y' * 1000)"),
            cwd=tmp_path,
            output_cap=32,
        )
    )
    assert bounded.truncated is True
    timed_out = process.run(
        ProcessRequest(
            tool_id="timeout",
            executable=sys.executable,
            args=(
                "-c",
                f"import pathlib,time; time.sleep(1); pathlib.Path(r'{tmp_path / 'late-marker'}').write_text('late')",
            ),
            cwd=tmp_path,
            timeout=0.03,
        )
    )
    assert timed_out.timed_out is True and timed_out.exit_code is not None
    assert not (tmp_path / "late-marker").exists()


def test_process_timeout_terminates_descendants_and_closes_pipes(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-late-marker"
    child = (
        f"import pathlib,time; time.sleep(0.3); pathlib.Path({str(marker)!r}).write_text('late')"
    )
    parent = (
        f"import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(1)"
    )
    output = SubprocessProcess().run(
        ProcessRequest(
            tool_id="descendant-timeout",
            executable=sys.executable,
            args=("-c", parent),
            cwd=tmp_path,
            timeout=0.03,
        )
    )
    assert output.timed_out is True
    time.sleep(0.4)
    assert not marker.exists()


def test_windows_tree_kill_falls_back_when_taskkill_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from repowise.core.analysis.analyzer_integration import process as process_module

    class Process:
        pid = 123

        def __init__(self) -> None:
            self.killed = False

        def kill(self) -> None:
            self.killed = True

    child = Process()
    calls: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(process_module.os, "name", "nt")
    monkeypatch.setattr(
        process_module.subprocess,
        "run",
        lambda *args, **kwargs: (calls.append((args[0], kwargs)), SimpleNamespace(returncode=1))[1],
    )

    process_module._terminate_process_tree(child)

    assert child.killed is True
    assert calls[0][0][0].lower().endswith("system32\\taskkill.exe")
    assert len(calls[0][0][0].split("\\")) > 1


def test_process_stdin_write_is_bounded_by_process_timeout(tmp_path: Path) -> None:
    started = time.perf_counter()
    output = SubprocessProcess().run(
        ProcessRequest(
            tool_id="stdin-timeout",
            executable=sys.executable,
            args=("-c", "import time; time.sleep(1)"),
            cwd=tmp_path,
            stdin=b"x" * (8 * 1024 * 1024),
            timeout=0.03,
        )
    )

    assert output.timed_out is True
    assert time.perf_counter() - started < 1.0


@pytest.mark.asyncio
async def test_lifecycle_retries_only_errors_and_keeps_score_opaque(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    attempts = 0

    def factory(context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return AnalyzerResult(
                analyzer_id="retry", analyzer_version="1", status=AnalyzerStatus.ERROR
            )
        return _result("retry")

    registry.register(_definition("retry"), factory)
    events: list[str] = []
    orchestrator = LifecycleOrchestrator(
        analyzer_registry=registry,
        composer=lambda context, results: {"opaque": True},
        hooks={
            "plan": lambda phase, value: events.append(phase),
            "publish": lambda phase, value: events.append(phase),
        },
        max_retries=1,
    )
    outcome = await orchestrator.run_repository(_context(tmp_path))
    assert outcome.status == "completed"
    assert outcome.score == {"opaque": True}
    assert attempts == 2
    assert events == ["plan", "publish"]


@pytest.mark.asyncio
async def test_lifecycle_dry_run_and_batch_order(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    registry.register(_definition("one"), lambda context: _result("one"))
    orchestrator = LifecycleOrchestrator(analyzer_registry=registry, max_concurrency=1)
    dry = await orchestrator.run_repository(_context(tmp_path), dry_run=True)
    assert dry.status == "skipped" and dry.results == ()
    batch = await orchestrator.run_batch(
        [_context(tmp_path, repo_id="b"), _context(tmp_path, repo_id="a")]
    )
    assert [outcome.repository_id for outcome in batch.outcomes] == ["b", "a"]


@pytest.mark.asyncio
async def test_lifecycle_checkpoint_failure_and_resume_replays_without_output_skip(
    tmp_path: Path,
) -> None:
    class Checkpoint:
        def __init__(self):
            self.state = None
            self.events = []

        async def begin(self, **kwargs):
            self.state = type(
                "State",
                (),
                {
                    "job_id": "job-1",
                    "metadata": {"run_key": kwargs["run_key"]},
                    "cursor": None,
                },
            )()
            self.events.append(("begin", kwargs["run_key"]))
            return self.state

        async def resume(self, **kwargs):
            self.events.append(("resume", kwargs["run_key"]))
            return self.state

        async def checkpoint(self, state, **kwargs):
            self.events.append(("checkpoint", kwargs["phase"], kwargs["completed"]))
            state.cursor = json.dumps(
                {"phase": kwargs["phase"], "completed": list(kwargs["completed"])}
            )

        async def complete(self, state, **kwargs):
            self.events.append(("complete", kwargs["phase"]))

        async def fail(self, state, **kwargs):
            self.events.append(("fail", kwargs["phase"], kwargs["error"]))

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    checkpoint = Checkpoint()
    fail_once = True

    async def persist(context, results, score):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("interrupted")

    orchestrator = LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
        composer=lambda context, results: {"score": 1},
        persist=persist,
        max_retries=0,
    )
    first = await orchestrator.run_repository(_context(tmp_path))
    second = await orchestrator.run_repository(_context(tmp_path), resume=True)
    assert first.status == "failed" and second.status == "completed"
    assert second.resumed is True
    assert any(event[0] == "fail" for event in checkpoint.events)
    assert any(event[0] == "resume" for event in checkpoint.events)


@pytest.mark.asyncio
async def test_lifecycle_checkpoint_start_failure_returns_isolated_outcome(tmp_path: Path) -> None:
    class FailingCheckpoint:
        async def begin(self, **kwargs):
            raise OSError("password=do-not-log")

        async def fail(self, state, **kwargs):
            raise AssertionError("fail must not receive missing state")

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=FailingCheckpoint(),
    ).run_repository(_context(tmp_path))
    assert outcome.status == "failed"
    assert outcome.error == "OSError"
    assert outcome.job_id is None


@pytest.mark.asyncio
async def test_lifecycle_checkpoint_transition_failure_isolated_with_created_state(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    class FailingCheckpoint:
        def __init__(self) -> None:
            self.last_state = type(
                "State",
                (),
                {
                    "job_id": "created-job",
                    "metadata": {
                        "run_key": run_key(context, None),
                        "repository_id": context.repo_id,
                    },
                },
            )()
            self.failed_state = None

        async def begin(self, **kwargs):
            raise OSError("checkpoint transition failed")

        async def fail(self, state, **kwargs):
            self.failed_state = state

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    checkpoint = FailingCheckpoint()

    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(context)

    assert outcome.status == "failed"
    assert outcome.job_id == "created-job"
    assert checkpoint.failed_state is checkpoint.last_state


@pytest.mark.asyncio
async def test_lifecycle_begin_failure_does_not_fail_a_foreign_stale_state(
    tmp_path: Path,
) -> None:
    class FailingCheckpoint:
        def __init__(self) -> None:
            self.last_state = type(
                "State",
                (),
                {
                    "job_id": "foreign-job",
                    "metadata": {"run_key": "another-run"},
                },
            )()
            self.failed_state = None

        async def begin(self, **kwargs: object) -> None:
            raise OSError("begin unavailable")

        async def fail(self, state: object, **kwargs: object) -> None:
            self.failed_state = state

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    checkpoint = FailingCheckpoint()

    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(_context(tmp_path))

    assert outcome.status == "failed"
    assert outcome.error == "OSError"
    assert outcome.job_id is None
    assert checkpoint.failed_state is None


@pytest.mark.asyncio
async def test_lifecycle_discards_foreign_resume_state_and_starts_fresh_run(
    tmp_path: Path,
) -> None:
    class Checkpoint:
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []
            self.current = type(
                "State",
                (),
                {"job_id": "fresh-job", "metadata": {}, "cursor": None},
            )()
            self.foreign = type(
                "State",
                (),
                {
                    "job_id": "foreign-job",
                    "metadata": {"run_key": "some-other-run"},
                    "cursor": json.dumps({"phase": "collect", "completed": ["plan"]}),
                },
            )()

        async def resume(self, **kwargs: object) -> object:
            self.events.append(("resume", kwargs["run_key"]))
            return self.foreign

        async def begin(self, **kwargs: object) -> object:
            self.current.metadata = {"run_key": kwargs["run_key"]}
            self.events.append(("begin", kwargs["run_key"]))
            return self.current

        async def checkpoint(self, state: object, **kwargs: object) -> None:
            assert state is self.current
            self.events.append(("checkpoint", kwargs["phase"]))

        async def complete(self, state: object, **kwargs: object) -> None:
            assert state is self.current
            self.events.append(("complete", kwargs["phase"]))

        async def fail(self, state: object, **kwargs: object) -> None:
            assert state is self.current
            self.events.append(("fail", kwargs["phase"]))

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    checkpoint = Checkpoint()
    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(_context(tmp_path), resume=True)

    assert outcome.status == "completed"
    assert outcome.resumed is False
    assert outcome.job_id == "fresh-job"
    assert [event[0] for event in checkpoint.events] == [
        "resume",
        "begin",
        "checkpoint",
        "checkpoint",
        "checkpoint",
        "checkpoint",
        "checkpoint",
        "checkpoint",
        "complete",
    ]


@pytest.mark.asyncio
async def test_lifecycle_dry_run_keeps_legacy_dry_run_cursor_and_resume_flag(
    tmp_path: Path,
) -> None:
    class Checkpoint:
        def __init__(self) -> None:
            self.state = type(
                "State",
                (),
                {"job_id": "dry-job", "metadata": {}, "cursor": None},
            )()
            self.completed: list[tuple[str, tuple[str, ...]]] = []

        async def begin(self, **kwargs: object) -> object:
            self.state.metadata = {"run_key": kwargs["run_key"]}
            return self.state

        async def resume(self, **kwargs: object) -> object | None:
            return None

        async def checkpoint(self, state: object, **kwargs: object) -> None:
            completed = tuple(kwargs["completed"])
            self.completed.append((str(kwargs["phase"]), completed))
            self.state.cursor = json.dumps({"phase": kwargs["phase"], "completed": list(completed)})

        async def complete(self, state: object, **kwargs: object) -> None:
            self.completed.append((str(kwargs["phase"]), tuple(kwargs["completed"])))
            self.state.cursor = json.dumps(
                {"phase": kwargs["phase"], "completed": list(kwargs["completed"])}
            )

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    checkpoint = Checkpoint()
    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(_context(tmp_path), dry_run=True)

    assert outcome.status == "skipped"
    assert outcome.phase == "collect"
    assert outcome.resumed is False
    assert json.loads(checkpoint.state.cursor)["phase"] == "dry-run"
    assert json.loads(checkpoint.state.cursor)["completed"] == ["plan", "collect"]


@pytest.mark.asyncio
async def test_lifecycle_resume_failure_isolated_without_missing_state_failure_call(
    tmp_path: Path,
) -> None:
    class FailingResume:
        async def resume(self, **kwargs: object) -> object:
            raise OSError("resume unavailable")

        async def begin(self, **kwargs: object) -> object:
            raise AssertionError("begin must not run after resume failure")

        async def fail(self, state: object, **kwargs: object) -> None:
            raise AssertionError("fail must not receive missing state")

    registry = AnalyzerRegistry()
    registry.register(_definition("fixture"), lambda context: _result("fixture"))
    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=FailingResume(),
    ).run_repository(_context(tmp_path), resume=True)

    assert outcome.status == "failed"
    assert outcome.error == "OSError"
    assert outcome.job_id is None


def test_finding_merge_preserves_first_owner_and_evidence_order(tmp_path: Path) -> None:
    first_ref = EvidenceRef(source="first", collected_at=datetime(2026, 9, 13, tzinfo=UTC))
    second_ref = EvidenceRef(source="second", collected_at=datetime(2026, 9, 13, tzinfo=UTC))
    first = Finding(
        id="first",
        analyzer_id="a",
        subject="Thing",
        dimension=" Code ",
        severity="low",
        confidence=0.4,
        reason="  Too   complex ",
        evidence_refs=(first_ref,),
        location=FindingLocation(path="x.py", line_start=1),
    )
    duplicate = first.model_copy(
        update={
            "id": "second",
            "analyzer_id": "b",
            "severity": "high",
            "confidence": 0.9,
            "evidence_refs": (second_ref,),
        }
    )
    results = (_result("a"), _result("b"))
    results = (
        results[0].model_copy(update={"findings": (first,)}),
        results[1].model_copy(update={"findings": (duplicate,)}),
    )
    merged = deduplicate_findings(results)
    assert len(merged[0].findings) == 1 and not merged[1].findings
    assert merged[0].findings[0].id == "first"
    assert [ref.source for ref in merged[0].findings[0].evidence_refs] == ["first", "second"]
    assert merged[0].findings[0].severity == "high"
