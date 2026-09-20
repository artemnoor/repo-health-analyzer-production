"""Focused deterministic old/new comparator for the integration boundary.

The health-edge imports in this file stay local on purpose.  This keeps the
neutral-core regressions runnable on their own while making any legacy health
dependency failure explicit in the acceptance tests that require it.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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
from repowise.core.analysis.analyzer_integration.finding_merge import finding_identity
from repowise.core.analysis.analyzer_integration.lifecycle import LifecycleOrchestrator
from repowise.core.analysis.analyzer_integration.registry import AnalyzerRegistry
from repowise.core.analysis.analyzer_integration.runner import run_json_command

_HEALTH_INTEGRATIONS = "packages/core/src/repowise/core/analysis/health/integrations"
_BASELINE_REF = "refactor/modularization"
_HEALTH_COVERAGE = "packages/core/src/repowise/core/analysis/health/coverage.py"
_LEGACY_INIT_UPDATE_REGRESSION_PATHS = (
    "tests/integration/test_cli.py",
    "tests/unit/cli/test_update_persist_reliability.py",
    "tests/unit/cli/test_update_phase_timings.py",
    "tests/unit/cli/test_health_persist_analyzed_commit.py",
    "tests/unit/cli/test_health_rescore_gate.py",
    "tests/unit/cli/test_rescore_rebuilds_read_models.py",
    "tests/unit/cli/test_init_noninteractive.py",
    "tests/unit/pipeline/test_init_update_graph_convergence.py",
    "tests/unit/pipeline/test_update_graph_convergence.py",
    "tests/unit/pipeline/test_resume.py",
    "tests/unit/pipeline/test_checkpoint.py",
    "tests/integration/test_pipeline_fast_checkpoint.py",
    "tests/integration/test_pipeline_resume.py",
)

# These are real legacy scenarios, not a file-presence checklist.  They are
# executed once from the immutable baseline checkout and once from the
# candidate checkout below.  The pair keeps the extraction gate honest even
# when a focused kernel test passes through a facade by accident.
_LEGACY_REGRESSION_SCENARIOS = (
    "tests/integration/test_cli.py::TestUpdateIndexOnly::test_advances_sync_commit",
    "tests/unit/health/test_native_adapters.py",
    "tests/unit/health/test_forge_adapters.py",
    "tests/unit/cli/test_update_persist_reliability.py::test_full_persist_collects_degraded_steps",
    "tests/unit/cli/test_update_phase_timings.py::test_index_only_update_writes_phase_timings",
    "tests/unit/cli/test_health_persist_analyzed_commit.py::test_persist_health_stamps_analyzed_commit",
    "tests/unit/cli/test_health_rescore_gate.py::TestFullRescoreDue::test_analyzer_change_fires_without_git",
    "tests/unit/cli/test_rescore_rebuilds_read_models.py::TestRescoreRebuildsTheReadModels::test_it_stamps_the_commit_it_scored_against",
    "tests/unit/cli/test_init_noninteractive.py::TestCostGate::test_non_tty_declines_without_prompting",
    "tests/unit/pipeline/test_init_update_graph_convergence.py::test_init_and_update_graphs_identical",
    "tests/unit/pipeline/test_update_graph_convergence.py::test_update_graph_converges_with_init_graph",
    "tests/unit/pipeline/test_resume.py::test_controller_skips_completed_index_on_resume",
    "tests/unit/pipeline/test_checkpoint.py::test_checkpointer_records_phase_lifecycle",
    "tests/integration/test_pipeline_fast_checkpoint.py::test_checkpoints_recorded_for_completed_phases",
    "tests/integration/test_pipeline_resume.py::test_resume_skips_index_compute",
    "tests/integration/test_health_replay_rescore.py::test_rescore_reuses_stored_metrics_and_marks_projection_recomputed",
    "tests/integration/test_health_replay_rescore.py::test_canonical_projection_is_identical_across_rest_mcp_and_cli",
)


def _git_baseline_source(repo_root: Path, relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{_BASELINE_REF}:{relative_path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _load_scoped_package(
    repo_root: Path,
    tmp_path: Path,
    package_label: str,
    sources: dict[str, str],
    *,
    baseline: bool,
) -> dict[str, ModuleType]:
    """Load selected modules from an isolated package namespace.

    ``baseline=True`` reads source only through ``git show HEAD:...``.  This
    keeps parity independent from the current health compatibility facade and
    avoids importing the known-missing health.coverage module.  Candidate
    modules are copied from the working tree into a different namespace, so
    neither side can satisfy imports from the other side by accident.
    """
    package_name = f"_aif_{package_label}_{tmp_path.name.replace('-', '_')}"
    package_dir = tmp_path / package_name
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    for module_name, relative_path in sources.items():
        target = package_dir / (module_name.replace(".", "/") + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in target.relative_to(package_dir).parents:
            if str(parent) != ".":
                (package_dir / parent / "__init__.py").touch()
        source = (
            _git_baseline_source(repo_root, relative_path)
            if baseline
            else (repo_root / relative_path).read_text(encoding="utf-8")
        )
        target.write_text(source, encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    try:
        return {
            module_name: importlib.import_module(f"{package_name}.{module_name}")
            for module_name in sources
        }
    finally:
        sys.path.remove(str(tmp_path))


def _install_preexisting_coverage_shim(repo_root: Path) -> None:
    """Ensure candidate parity tests use the real production coverage package."""
    del repo_root
    importlib.import_module("repowise.core.analysis.health.coverage")


@pytest.fixture(scope="module", autouse=True)
def _restore_parity_coverage_shim(repo_root: Path):
    """Keep the real production coverage package available for this module."""
    _install_preexisting_coverage_shim(repo_root)
    yield


def _context(
    repo_path: Path | None = None,
    *,
    repo_id: str = "fixture",
    mode: str = "fast",
    capabilities: tuple[str, ...] = ("scan",),
) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=repo_path or Path("."),
        repo_id=repo_id,
        head_sha="head",
        as_of_ts=datetime(2026, 9, 13, tzinfo=UTC),
        mode=mode,
        capabilities=capabilities,
    )


def _without_volatile_fields(value: Any) -> Any:
    """Exclude only runtime fields from public projection comparisons."""
    if isinstance(value, dict):
        return {
            key: _without_volatile_fields(item)
            for key, item in value.items()
            if key not in {"duration_ms", "generated_at"}
        }
    if isinstance(value, list):
        return [_without_volatile_fields(item) for item in value]
    return value


def test_old_init_update_regression_surface_is_present(repo_root: Path) -> None:
    """Keep the executable gate tied to every required regression module."""
    missing = [
        path for path in _LEGACY_INIT_UPDATE_REGRESSION_PATHS if not (repo_root / path).is_file()
    ]
    assert not missing, f"missing legacy init/update regression files: {missing}"


def _write_coverage_sitecustomize(path: Path, *, legacy_overlay: Path | None = None) -> None:
    """Prepare a child-process path; shim only the immutable baseline."""
    coverage_bootstrap = (
        """
import sys
from pathlib import Path
from types import ModuleType

name = 'repowise.core.analysis.health.coverage'
module = ModuleType(name, 'TEST-ONLY shim for the immutable baseline gap')
module.is_test_file = lambda value: Path(str(value)).name.startswith('test_')
module.decay_since = lambda *args, **kwargs: {}
module.measurement_ref = lambda *args, **kwargs: None
module.discover_artifacts = lambda *args, **kwargs: []
module.build_coverage_map = lambda *args, **kwargs: ({}, [])
class CoverageConfig:
    paths = ()
    artifacts = ()
    auto_discover = False
    reingest_on_update = False
    format = None
    strip_prefix = None
    path_prefix = None
    @classmethod
    def from_repo_config(cls, config):
        return cls()
module.CoverageConfig = CoverageConfig
sys.modules.setdefault(name, module)
parent = __import__('repowise.core.analysis.health', fromlist=['*'])
setattr(parent, 'coverage', module)
""".lstrip()
        if legacy_overlay is not None
        else ""
    )
    path.write_text(coverage_bootstrap,
        encoding="utf-8",
    )
    if legacy_overlay is not None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"""
import importlib.util
from pathlib import Path

legacy_root = Path({str(legacy_overlay)!r})
class LegacyFinder:
    modules = {{
        'repowise.core.analysis.health.integrations.contracts': 'contracts.py',
        'repowise.core.analysis.health.integrations.registry': 'registry.py',
        'repowise.core.analysis.health.integrations.runner': 'runner.py',
        'repowise.core.analysis.health.integrations.process': 'process.py',
        'repowise.core.analysis.health.integrations.finding_merge': 'finding_merge.py',
    }}
    def find_spec(self, fullname, path=None, target=None):
        filename = self.modules.get(fullname)
        if filename is None:
            return None
        return importlib.util.spec_from_file_location(fullname, legacy_root / filename)
sys.meta_path.insert(0, LegacyFinder())
""".lstrip()
            )


def _run_regression_scenarios(
    repo_root: Path, *, shim_dir: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    source_roots = [
        str(shim_dir),
        str(repo_root / "packages" / "core" / "src"),
        str(repo_root / "packages" / "cli" / "src"),
        str(repo_root),
    ]
    existing_pythonpath = environment.get("PYTHONPATH")
    if existing_pythonpath:
        source_roots.append(existing_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(source_roots)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            "--maxfail=1",
            *_LEGACY_REGRESSION_SCENARIOS,
        ],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def test_old_and_candidate_execute_real_init_update_regression_scenarios(
    tmp_path: Path, repo_root: Path
) -> None:
    """Execute the real legacy scenarios independently on both code lines.

    The baseline subprocess overlays every legacy integration module directly
    from ``refactor/modularization``; no current integration facade can satisfy
    its imports.  The same scenario list covers fixture-backed CLI init/update,
    persistence and timing, noninteractive init, rescore/replay, REST/MCP/CLI
    projection, and graph/checkpoint convergence.  The shim is process-local
    and asserts the known missing baseline module without adding a product
    file.
    """
    assert not (repo_root / _HEALTH_COVERAGE).is_file()
    baseline_probe = subprocess.run(
        ["git", "cat-file", "-e", f"{_BASELINE_REF}:{_HEALTH_COVERAGE}"],
        cwd=repo_root,
        capture_output=True,
    )
    assert baseline_probe.returncode != 0

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    _write_coverage_sitecustomize(shim_dir / "sitecustomize.py")

    candidate = _run_regression_scenarios(repo_root, shim_dir=shim_dir)
    assert candidate.returncode == 0, (
        f"candidate legacy regression scenarios failed:\n{candidate.stdout}\n{candidate.stderr}"
    )

    baseline_root = tmp_path / "baseline-integrations"
    baseline_root.mkdir()
    for source_path in (repo_root / _HEALTH_INTEGRATIONS).glob("*.py"):
        relative_path = f"{_HEALTH_INTEGRATIONS}/{source_path.name}"
        baseline_file = subprocess.run(
            ["git", "cat-file", "-e", f"{_BASELINE_REF}:{relative_path}"],
            cwd=repo_root,
            capture_output=True,
        )
        if baseline_file.returncode != 0:
            # New adapters are candidate-only by definition. They must not be
            # overlaid into the immutable legacy baseline subprocess.
            continue
        target = baseline_root / source_path.name
        target.write_text(
            _git_baseline_source(
                repo_root,
                relative_path,
            ),
            encoding="utf-8",
        )
    baseline_shim = tmp_path / "baseline-shim"
    baseline_shim.mkdir()
    _write_coverage_sitecustomize(baseline_shim / "sitecustomize.py", legacy_overlay=baseline_root)
    baseline = _run_regression_scenarios(repo_root, shim_dir=baseline_shim)
    assert baseline.returncode == 0, (
        f"immutable legacy regression scenarios failed:\n{baseline.stdout}\n{baseline.stderr}"
    )


def test_legacy_and_neutral_execution_have_identical_deterministic_shape(
    tmp_path: Path, repo_root: Path
) -> None:
    baseline = _load_scoped_package(
        repo_root,
        tmp_path,
        "baseline_registry",
        {
            "contracts": f"{_HEALTH_INTEGRATIONS}/contracts.py",
            "registry": f"{_HEALTH_INTEGRATIONS}/registry.py",
            "runner": f"{_HEALTH_INTEGRATIONS}/runner.py",
        },
        baseline=True,
    )
    baseline_contracts = baseline["contracts"]
    baseline_registry_type = baseline["registry"].AnalyzerRegistry
    assert baseline_registry_type.__module__ != AnalyzerRegistry.__module__
    assert "class AnalyzerRegistry" in _git_baseline_source(
        repo_root, f"{_HEALTH_INTEGRATIONS}/registry.py"
    )

    definition = AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none")

    def factory(context: AnalyzerContext) -> AnalyzerResult:
        evidence = EvidenceRef(
            source="fixture.json",
            source_commit=context.head_sha,
            tool_version="fixture-1",
            path="src/example.py",
            line_start=4,
            line_end=5,
            json_pointer="/score",
            snippet_hash="abc",
            collected_at=context.as_of_ts,
            confidence=0.9,
            redaction="none",
        )
        return AnalyzerResult(
            analyzer_id="fixture",
            analyzer_version="1",
            status=AnalyzerStatus.PASS,
            score=88,
            score_dimension="code",
            metrics=(
                MetricValue(
                    name="fixture.score",
                    dimension="code",
                    value=88,
                    unit="points",
                    score=88,
                    population=1,
                    denominator=1,
                    evidence_refs=(evidence,),
                ),
            ),
            findings=(
                Finding(
                    id="finding-1",
                    analyzer_id="fixture",
                    subject="example.py",
                    dimension="code",
                    severity="medium",
                    confidence=0.8,
                    reason="fixture finding",
                    evidence_refs=(evidence,),
                    location=FindingLocation(path="src/example.py", line_start=4, line_end=5),
                    remediation="fix it",
                    raw_impact=0.4,
                    applied_impact=0.3,
                ),
            ),
            evidence=(evidence,),
            limitations=(Limitation(reason="fixture limitation", kind="other"),),
            source_versions={"fixture": "1"},
            raw_payload_ref="fixture/raw.json",
            diagnostics={"fixture": True},
            available_weight=1,
            total_weight=1,
        )

    context = _context(tmp_path)
    old_context = baseline_contracts.AnalyzerContext.model_validate(context.model_dump(mode="json"))

    new_registry = AnalyzerRegistry()
    old_registry = baseline_registry_type()
    new_registry.register(definition, factory)
    old_definition = baseline_contracts.AnalyzerDefinition.model_validate(
        definition.model_dump(mode="json")
    )

    def old_factory(old_context_value: Any) -> Any:
        candidate_result = factory(old_context_value)
        return baseline_contracts.AnalyzerResult.model_validate(
            candidate_result.model_dump(mode="json")
        )

    old_registry.register(old_definition, old_factory)
    new_result = new_registry.run(new_registry.plan(context)[0], context)
    old_result = old_registry.run(old_registry.plan(old_context)[0], old_context)
    new_dump = new_result.model_dump(mode="json")
    old_dump = old_result.model_dump(mode="json")
    new_dump.pop("duration_ms")
    old_dump.pop("duration_ms")
    assert old_dump == new_dump


@pytest.mark.asyncio
async def test_resume_without_a_matching_checkpoint_is_not_reported_as_resumed(
    tmp_path: Path,
) -> None:
    class Checkpoint:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def resume(self, **kwargs: Any) -> None:
            self.events.append("resume")
            return None

        async def begin(self, **kwargs: Any) -> object:
            self.events.append("begin")
            return type("State", (), {"job_id": "new-job"})()

        async def checkpoint(self, state: object, **kwargs: Any) -> None:
            return None

        async def complete(self, state: object, **kwargs: Any) -> None:
            return None

    registry = AnalyzerRegistry()
    definition = AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none")
    registry.register(
        definition,
        lambda context: AnalyzerResult(
            analyzer_id="fixture", analyzer_version="1", status=AnalyzerStatus.PASS
        ),
    )
    checkpoint = Checkpoint()

    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(_context(tmp_path), resume=True)

    assert outcome.status == "completed"
    assert outcome.job_id == "new-job"
    assert outcome.resumed is False
    assert checkpoint.events == ["resume", "begin"]


@pytest.mark.asyncio
async def test_resume_discards_foreign_or_invalid_checkpoint_and_starts_fresh_run(
    tmp_path: Path,
) -> None:
    class Checkpoint:
        def __init__(self, cursor: str) -> None:
            self.cursor = cursor
            self.events: list[str] = []

        async def resume(self, **kwargs: Any) -> object:
            self.events.append("resume")
            return type(
                "ForeignState",
                (),
                {
                    "job_id": "foreign-job",
                    "metadata": {"run_key": "another-run"},
                    "cursor": self.cursor,
                },
            )()

        async def begin(self, **kwargs: Any) -> object:
            self.events.append("begin")
            return type("FreshState", (), {"job_id": "fresh-job"})()

        async def checkpoint(self, state: object, **kwargs: Any) -> None:
            self.events.append(f"checkpoint:{kwargs['phase']}")

        async def complete(self, state: object, **kwargs: Any) -> None:
            self.events.append("complete")

    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        lambda context: AnalyzerResult(
            analyzer_id="fixture", analyzer_version="1", status=AnalyzerStatus.PASS
        ),
    )

    for cursor in ('{"phase":"plan","completed":["plan"]}', "not-json"):
        checkpoint = Checkpoint(cursor)
        outcome = await LifecycleOrchestrator(
            analyzer_registry=registry,
            checkpoint=checkpoint,
        ).run_repository(_context(tmp_path), resume=True)
        assert outcome.status == "completed"
        assert outcome.resumed is False
        assert outcome.job_id == "fresh-job"
        assert checkpoint.events[0:2] == ["resume", "begin"]
        assert "complete" in checkpoint.events


@pytest.mark.asyncio
async def test_resume_checkpoint_failure_returns_isolated_outcome_without_fail_none(
    tmp_path: Path,
) -> None:
    class Checkpoint:
        def __init__(self) -> None:
            self.fail_called = False

        async def resume(self, **kwargs: Any) -> object:
            raise OSError("resume backend unavailable")

        async def fail(self, state: object, **kwargs: Any) -> None:
            self.fail_called = True
            assert state is not None

    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        lambda context: AnalyzerResult(
            analyzer_id="fixture", analyzer_version="1", status=AnalyzerStatus.PASS
        ),
    )
    checkpoint = Checkpoint()
    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(_context(tmp_path), resume=True)
    assert outcome.status == "failed"
    assert outcome.error == "OSError"
    assert checkpoint.fail_called is False


@pytest.mark.asyncio
async def test_dry_run_preserves_checkpoint_cursor_and_result_semantics(tmp_path: Path) -> None:
    class Checkpoint:
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []

        async def resume(self, **kwargs: Any) -> None:
            self.events.append(("resume", kwargs["run_key"]))
            return None

        async def begin(self, **kwargs: Any) -> object:
            self.events.append(("begin", kwargs["run_key"]))
            return type("State", (), {"job_id": "dry-run-job"})()

        async def checkpoint(self, _state: object, **kwargs: Any) -> None:
            self.events.append(("checkpoint", (kwargs["phase"], kwargs["completed"])))

        async def complete(self, _state: object, **kwargs: Any) -> None:
            self.events.append(("complete", (kwargs["phase"], kwargs["completed"])))

    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        lambda context: AnalyzerResult(
            analyzer_id="fixture", analyzer_version="1", status=AnalyzerStatus.PASS
        ),
    )
    checkpoint = Checkpoint()

    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        checkpoint=checkpoint,
    ).run_repository(_context(tmp_path), resume=True, dry_run=True)

    assert outcome.status == "skipped"
    assert outcome.phase == "collect"
    assert outcome.results == ()
    assert outcome.resumed is False
    assert outcome.dry_run is True
    assert outcome.job_id == "dry-run-job"
    assert checkpoint.events[-1] == ("complete", ("dry-run", ("plan", "collect")))


@pytest.mark.asyncio
async def test_resume_without_checkpoint_port_is_not_reported_as_resumed(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture", version="1", category="test", cache_policy="none"),
        lambda context: AnalyzerResult(
            analyzer_id="fixture", analyzer_version="1", status=AnalyzerStatus.PASS
        ),
    )

    outcome = await LifecycleOrchestrator(analyzer_registry=registry).run_repository(
        _context(tmp_path), resume=True
    )

    assert outcome.status == "completed"
    assert outcome.resumed is False
    assert outcome.job_id is None


def test_finding_identity_matches_immutable_legacy_contract(
    tmp_path: Path, repo_root: Path
) -> None:
    baseline = _load_scoped_package(
        repo_root,
        tmp_path,
        "baseline_finding",
        {
            "contracts": f"{_HEALTH_INTEGRATIONS}/contracts.py",
            "finding_merge": f"{_HEALTH_INTEGRATIONS}/finding_merge.py",
        },
        baseline=True,
    )
    finding = Finding(
        id="finding",
        analyzer_id="fixture",
        subject="Thing Name",
        dimension="code quality",
        severity="medium",
        confidence=0.8,
        reason="Too complex",
        location=FindingLocation(path="src/example file.py", line_start=4),
    )

    old_finding = baseline["contracts"].Finding.model_validate(finding.model_dump(mode="json"))
    assert finding_identity(finding) == baseline["finding_merge"]._identity(old_finding)
    assert finding_identity(
        finding.model_copy(update={"reason": "Too   complex"})
    ) == finding_identity(finding)
    assert finding_identity(
        finding.model_copy(update={"dimension": "code  quality"})
    ) != finding_identity(finding)
    assert finding_identity(
        finding.model_copy(update={"subject": "Thing  Name"})
    ) != finding_identity(finding)
    assert finding_identity(
        finding.model_copy(
            update={"location": FindingLocation(path="src/example  file.py", line_start=4)}
        )
    ) != finding_identity(finding)


def test_run_json_command_uses_the_bounded_allowlisted_process_boundary(tmp_path: Path) -> None:
    result = run_json_command(
        [
            sys.executable,
            "-c",
            "import json,os; print(json.dumps({'secret': os.getenv('PARITY_SECRET', 'missing')}))",
        ],
        cwd=tmp_path,
        timeout=2,
    )

    assert result == {"secret": "missing"}


def test_run_json_command_delegates_request_shape_to_process_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repowise.core.analysis.analyzer_integration import runner as runner_module
    from repowise.core.analysis.analyzer_integration.process import ProcessOutput

    requests: list[Any] = []

    class FakeProcess:
        def run(self, request: Any) -> ProcessOutput:
            requests.append(request)
            return ProcessOutput(
                tool_id=request.tool_id,
                exit_code=0,
                stdout='{"fixture": true}',
                stderr="",
                duration_ms=1,
            )

    monkeypatch.setattr(runner_module, "SubprocessProcess", FakeProcess)
    assert run_json_command(["fixture-tool", "--json"], cwd=tmp_path, timeout=3.5) == {
        "fixture": True
    }
    assert len(requests) == 1
    assert requests[0].executable == "fixture-tool"
    assert requests[0].args == ("--json",)
    assert requests[0].cwd == tmp_path
    assert requests[0].timeout == 3.5
    assert requests[0].output_cap > 0


def test_run_json_command_accepts_an_injected_process_executor(tmp_path: Path) -> None:
    from repowise.core.analysis.analyzer_integration.process import ProcessOutput

    class FakeProcess:
        def run(self, request: Any) -> ProcessOutput:
            assert request.tool_id == "native-json"
            return ProcessOutput(
                tool_id=request.tool_id,
                exit_code=0,
                stdout='{"injected": true}',
                stderr="",
                duration_ms=1,
            )

    assert run_json_command(
        ["not-used"], cwd=tmp_path, timeout=1, process_executor=FakeProcess()
    ) == {"injected": True}


def test_run_json_command_preserves_missing_executable_exception(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_json_command([str(tmp_path / "missing-native-analyzer")], cwd=tmp_path, timeout=2)


def test_runner_failure_payload_matches_legacy_shape(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="invalid", version="1", category="test", cache_policy="none"),
        lambda context: {"not": "an analyzer result"},
    )
    result = registry.run(registry.plan(_context(tmp_path))[0], _context(tmp_path))
    assert result.status is AnalyzerStatus.ERROR
    assert result.limitations[0].reason == "invalid analyzer result: ValidationError"
    assert result.limitations[0].kind == "error"
    assert result.diagnostics == {}


def test_runner_timeout_payload_matches_legacy_shape(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()

    def slow(context: AnalyzerContext) -> AnalyzerResult:
        import time

        time.sleep(0.05)
        return AnalyzerResult(analyzer_id="slow", analyzer_version="1", status=AnalyzerStatus.PASS)

    registry.register(
        AnalyzerDefinition(
            id="slow", version="1", category="test", cache_policy="none", timeout=0.001
        ),
        slow,
    )
    result = registry.run(registry.plan(_context(tmp_path))[0], _context(tmp_path))
    assert result.status is AnalyzerStatus.ERROR
    assert result.limitations[0].reason == "analyzer timed out"
    assert result.limitations[0].kind == "timeout"
    assert result.diagnostics == {}


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    (
        ("scorecard/sample.json", AnalyzerStatus.WARN),
        ("repohealth/sample.json", AnalyzerStatus.WARN),
        ("criticality/sample.csv", AnalyzerStatus.PASS),
        ("qlty/sarif.json", AnalyzerStatus.FAIL),
        ("qlty/rdjson.json", AnalyzerStatus.WARN),
        ("sokrates/sample-export.json", AnalyzerStatus.WARN),
    ),
)
def test_real_native_fixtures_have_old_new_result_parity(
    tmp_path: Path,
    repo_root: Path,
    fixture_name: str,
    expected_status: AnalyzerStatus,
) -> None:
    baseline = _load_scoped_package(
        repo_root,
        tmp_path,
        "baseline_native",
        {
            "contracts": f"{_HEALTH_INTEGRATIONS}/contracts.py",
            "process": f"{_HEALTH_INTEGRATIONS}/process.py",
            "native_adapters": f"{_HEALTH_INTEGRATIONS}/native_adapters.py",
            "registry": f"{_HEALTH_INTEGRATIONS}/registry.py",
            "runner": f"{_HEALTH_INTEGRATIONS}/runner.py",
        },
        baseline=True,
    )
    candidate = _load_scoped_package(
        repo_root,
        tmp_path,
        "candidate_native",
        {
            "contracts": f"{_HEALTH_INTEGRATIONS}/contracts.py",
            "process": f"{_HEALTH_INTEGRATIONS}/process.py",
            "native_adapters": f"{_HEALTH_INTEGRATIONS}/native_adapters.py",
        },
        baseline=False,
    )

    fixture_path = repo_root / "tests" / "fixtures" / "native" / fixture_name
    payload: object = (
        fixture_path.read_text(encoding="utf-8")
        if fixture_path.suffix == ".csv"
        else json.loads(fixture_path.read_text(encoding="utf-8"))
    )
    analyzer_id = fixture_path.parent.name
    context = _context(
        tmp_path,
        repo_id=f"{analyzer_id}-fixture",
        mode="full",
        capabilities=(
            ("criticality_csv", "tool:criticality-score")
            if analyzer_id == "criticality"
            else ("local_scan", f"tool:{analyzer_id}")
        ),
    )

    def parse_fixture(parser: ModuleType, payload_value: object, ctx: Any, raw_ref: str) -> Any:
        if analyzer_id == "scorecard":
            return parser.parse_scorecard(payload_value, ctx, raw_ref=raw_ref)
        if analyzer_id == "repohealth":
            return parser.parse_repohealth(payload_value, ctx, raw_ref=raw_ref)
        if analyzer_id == "criticality":
            return parser.parse_criticality_csv(str(payload_value), ctx, raw_ref=raw_ref)
        if analyzer_id == "qlty":
            return parser.parse_qlty(payload_value, ctx, raw_ref=raw_ref)
        if analyzer_id == "sokrates":
            return parser.parse_sokrates(payload_value, ctx, raw_ref=raw_ref)
        raise AssertionError(f"unhandled native fixture: {fixture_name}")

    definitions = {
        "scorecard": "SCORECARD_DEFINITION",
        "repohealth": "REPOHEALTH_DEFINITION",
        "criticality": "CRITICALITY_DEFINITION",
        "qlty": "QLTY_DEFINITION",
        "sokrates": "SOKRATES_DEFINITION",
    }
    new_definition = getattr(candidate["native_adapters"], definitions[analyzer_id])
    old_definition = baseline["contracts"].AnalyzerDefinition.model_validate(
        getattr(baseline["native_adapters"], definitions[analyzer_id]).model_dump(mode="json")
    )
    old_context = baseline["contracts"].AnalyzerContext.model_validate(
        context.model_dump(mode="json")
    )

    new_registry = AnalyzerRegistry()
    old_registry = baseline["registry"].AnalyzerRegistry()
    new_registry.register(
        new_definition,
        lambda ctx: parse_fixture(
            candidate["native_adapters"], payload, ctx, f"native://fixture/{fixture_name}"
        ),
    )
    old_registry.register(
        old_definition,
        lambda ctx: baseline["contracts"].AnalyzerResult.model_validate(
            parse_fixture(
                baseline["native_adapters"], payload, ctx, f"native://fixture/{fixture_name}"
            ).model_dump(mode="json")
        ),
    )
    new_result = new_registry.run(new_registry.plan(context)[0], context)
    old_result = old_registry.run(old_registry.plan(old_context)[0], old_context)

    new_dump = new_result.model_dump(mode="json")
    old_dump = old_result.model_dump(mode="json")
    new_dump.pop("duration_ms")
    old_dump.pop("duration_ms")
    assert old_dump == new_dump
    assert new_result.status is expected_status
    assert old_result.status.value == expected_status.value
    assert new_result.raw_payload_ref == f"native://fixture/{fixture_name}"


@pytest.mark.asyncio
async def test_health_composition_injection_matches_immutable_legacy_composition(
    tmp_path: Path, repo_root: Path
) -> None:
    baseline = _load_scoped_package(
        repo_root,
        tmp_path,
        "baseline_composite",
        {
            "integrations.contracts": f"{_HEALTH_INTEGRATIONS}/contracts.py",
            "composite": "packages/core/src/repowise/core/analysis/health/composite.py",
        },
        baseline=True,
    )
    candidate = _load_scoped_package(
        repo_root,
        tmp_path,
        "candidate_composite",
        {
            "integrations.contracts": f"{_HEALTH_INTEGRATIONS}/contracts.py",
            "composite": "packages/core/src/repowise/core/analysis/health/composite.py",
        },
        baseline=False,
    )
    compose_health_score = candidate["composite"].compose_health_score

    collected_at = datetime(2026, 9, 13, tzinfo=UTC)
    evidence = EvidenceRef(source="fixture", collected_at=collected_at, confidence=0.9)
    result = AnalyzerResult(
        analyzer_id="fixture.code",
        analyzer_version="1",
        status=AnalyzerStatus.PASS,
        metrics=(
            MetricValue(
                name="fixture.code",
                dimension="code",
                score=82,
                denominator=1,
                evidence_refs=(evidence,),
            ),
        ),
        evidence=(evidence,),
        available_weight=1,
        total_weight=1,
    )
    old_result = baseline["integrations.contracts"].AnalyzerResult.model_validate(
        result.model_dump(mode="json")
    )
    expected = baseline["composite"].compose_health_score((old_result,), repository_id="fixture")
    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerDefinition(id="fixture.code", version="1", category="test", cache_policy="none"),
        lambda context: result,
    )
    outcome = await LifecycleOrchestrator(
        analyzer_registry=registry,
        composer=lambda context, results: compose_health_score(
            results, repository_id=context.repo_id
        ),
    ).run_repository(_context(tmp_path))

    assert outcome.score is not None
    assert outcome.score.model_dump(mode="json") == expected.model_dump(mode="json")


@pytest.fixture
async def canonical_session(tmp_path: Path, repo_root: Path):
    _install_preexisting_coverage_shim(repo_root)
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from repowise.core.persistence.database import init_db

    db_path = tmp_path / "canonical-parity.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.info["session_factory"] = factory
        session.info["db_url"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_rest_mcp_cli_canonical_projection_parity(
    canonical_session: Any,
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST, MCP and CLI expose the same persisted canonical read model."""
    _install_preexisting_coverage_shim(repo_root)
    from repowise.core.persistence.models import (
        HealthRecommendation,
        HealthScoreProjection,
        RepositoryHealthSnapshot,
    )
    from tests.unit.persistence.helpers import insert_repo

    repo_path = tmp_path / "repository"
    repo = await insert_repo(canonical_session, name="parity-health", local_path=str(repo_path))
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
    canonical_session.add(snapshot)
    await canonical_session.flush()
    canonical_session.add(
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
    canonical_session.add(
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
    await canonical_session.commit()

    from repowise.server.routers.code_health.canonical_routes import canonical_health

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
        session=canonical_session,
    )

    import repowise.server.mcp_server as mcp_mod

    mcp_mod._session_factory = canonical_session.info["session_factory"]
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

    monkeypatch.setenv("REPOWISE_DB_URL", canonical_session.info["db_url"])
    from repowise.cli.commands.health_cmd.persist import _load_canonical_health

    cli = await asyncio.to_thread(
        _load_canonical_health,
        repo_path,
        scope="all",
        include_evidence=True,
    )

    assert cli is not None
    assert _without_volatile_fields(rest) == _without_volatile_fields(mcp["canonical"])
    assert _without_volatile_fields(rest) == _without_volatile_fields(cli)


def test_legacy_init_update_index_only_regression(
    tmp_path: Path,
    sample_repo_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing init/update path still advances its persisted sync cursor."""
    _install_preexisting_coverage_shim(repo_root)
    health_module = importlib.import_module("repowise.core.analysis.health")
    monkeypatch.setitem(
        health_module.__dict__,
        "HealthAnalyzer",
        type("TestOnlyHealthAnalyzer", (), {}),
    )
    monkeypatch.setitem(health_module.__dict__, "HEALTH_ANALYZER_VERSION", "10")
    from click.testing import CliRunner

    from repowise.cli.main import cli

    repo = tmp_path / "init-update-repo"
    shutil.copytree(sample_repo_path, repo)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    git_add = ["git", "add", "-A", "--", ":!.repowise/lancedb"]
    subprocess.run(git_add, cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Parity",
            "-c",
            "user.email=parity@example.invalid",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    runner = CliRunner()
    initialized = runner.invoke(cli, ["init", str(repo), "--index-only"])
    assert initialized.exit_code == 0, initialized.output
    first_state = json.loads((repo / ".repowise" / "state.json").read_text(encoding="utf-8"))
    first_commit = first_state["last_sync_commit"]

    (repo / "parity_module.py").write_text(
        "def parity_fixture():\n    return 1\n", encoding="utf-8"
    )
    subprocess.run(git_add, cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Parity",
            "-c",
            "user.email=parity@example.invalid",
            "commit",
            "-m",
            "update",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    updated = runner.invoke(cli, ["update", str(repo), "--index-only"])
    assert updated.exit_code == 0, updated.output
    second_state = json.loads((repo / ".repowise" / "state.json").read_text(encoding="utf-8"))
    assert second_state["last_sync_commit"] != first_commit


EXPECTED_ANALYZER_IDS = (
    "chaoss.activity",
    "chaoss.dependencies",
    "chaoss.issues_prs",
    "chaoss.releases",
    "cicd.sourcecraft",
    "criticality.importance",
    "dependencies.enrichment",
    "events.temporal",
    "forge.community",
    "forge.metadata",
    "graal.external_tools",
    "identity.enrichment",
    "qlty.check",
    "repohealth.baseline",
    "repowise.health",
    "scorecard.local",
    "sokrates.analysis",
    "sourcecraft.appsec",
    "vale.documentation",
)


def test_registered_health_analyzer_matrix_remains_compatible(repo_root: Path) -> None:
    _install_preexisting_coverage_shim(repo_root)
    from repowise.core.analysis.health.integrations import register_all_health_adapters

    health = AnalyzerRegistry()
    register_all_health_adapters(health)
    first = health.ids()
    register_all_health_adapters(health)

    assert first == EXPECTED_ANALYZER_IDS
    assert health.ids() == first
    assert all(health.get(analyzer_id) is not None for analyzer_id in first)
    assert all(
        definition.version and definition.category and definition.timeout > 0
        for definition in health.definitions()
    )
