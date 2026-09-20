"""Contract and integration tests for the Vale documentation adapter."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from repowise.core.analysis.analyzer_integration.cache import cache_key
from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
)
from repowise.core.analysis.analyzer_integration.process import ProcessOutput

ROOT = Path(__file__).resolve().parents[3]

from repowise.core.analysis.health.integrations.contracts import AnalyzerDefinition  # noqa: E402
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry  # noqa: E402
from repowise.core.analysis.health.integrations.vale_adapter import (  # noqa: E402
    VALE_ANALYZER_ID,
    VALE_DEFINITION,
    VALE_SOURCE_COMMIT,
    ValeAdapter,
    ValePayloadError,
    batch_documentation_files,
    discover_documentation_files,
    load_vale_policy,
    parse_diagnostics,
    parse_metrics,
    register_vale_adapter,
)

vale_module = importlib.import_module("repowise.core.analysis.health.integrations.vale_adapter")
from repowise.core.analysis.health.composite import compose_health_score  # noqa: E402


class FakeProcess:
    def __init__(self, *outputs: ProcessOutput) -> None:
        self.outputs = list(outputs)
        self.requests: list[Any] = []

    def run(self, request: Any) -> ProcessOutput:
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("Vale adapter invoked an unexpected process phase")
        return self.outputs.pop(0)


def _output(
    stdout: str,
    *,
    exit_code: int | None = 0,
    stderr: str = "",
    timed_out: bool = False,
    truncated: bool = False,
    start_error: OSError | None = None,
) -> ProcessOutput:
    return ProcessOutput(
        tool_id=VALE_ANALYZER_ID,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=1,
        timed_out=timed_out,
        truncated=truncated,
        start_error=start_error,
    )


def _context(repo: Path, *, vale_available: bool = True) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=repo,
        repo_id="vale-test-repository",
        head_sha="a" * 40,
        as_of_ts=datetime(2026, 9, 18, tzinfo=UTC),
        capabilities=("local_scan",),
        tool_paths={"vale": sys.executable} if vale_available else {},
    )


def _write_readme(repo: Path, content: str = "A clean documentation paragraph.") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text(content, encoding="utf-8")


def _diagnostic(
    *,
    check: str,
    severity: str,
    message: str,
    line: int,
    match: str,
) -> dict[str, object]:
    return {
        "Check": check,
        "Severity": severity,
        "Message": message,
        "Line": line,
        "Span": [1, max(1, len(match))],
        "Match": match,
    }


def _metric(result: AnalyzerResult, name: str):
    return next(metric for metric in result.metrics if metric.name == name)


def test_policy_is_versioned_and_supported_files_are_deterministic() -> None:
    policy = load_vale_policy(ROOT)
    assert policy.tool_version == "3.22.0"
    assert policy.revision == "vale-3.22.0-policy-v2"
    assert policy.digest
    assert VALE_DEFINITION.version.startswith("vale-3.22.0-policy-v2-")

    files = discover_documentation_files(
        ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916", policy
    )
    assert files == tuple(sorted(files))
    assert all(
        path.casefold().endswith((".md", ".mdx", ".markdown", ".rst", ".txt")) for path in files
    )


def test_parse_diagnostics_normalizes_findings_and_rejects_escape(tmp_path: Path) -> None:
    payload = {
        "README.md": [
            _diagnostic(
                check="RepoHealth.Clarity",
                severity="warning",
                message="Use a precise description.",
                line=3,
                match="AWS-shaped",
            ),
            _diagnostic(
                check="RepoHealth.Terminology",
                severity="error",
                message="Use SourceCraft.",
                line=4,
                match="sourcecraft",
            ),
            _diagnostic(
                check="RepoHealth.Style",
                severity="suggestion",
                message="Prefer a direct sentence.",
                line=5,
                match="perhaps",
            ),
            _diagnostic(
                check="RepoHealth.Fatal",
                severity="fatal",
                message="Documentation cannot be parsed.",
                line=6,
                match="broken",
            ),
        ]
    }
    facts = parse_diagnostics(payload, tmp_path)

    assert [item.file for item in facts] == ["README.md"] * 4
    assert [item.severity for item in facts] == ["warning", "error", "suggestion", "fatal"]
    assert facts[0].line == 3
    assert facts[0].match == "AWS-shaped"
    assert facts[0].finding_id == facts[0].finding_id
    with pytest.raises(ValePayloadError):
        parse_diagnostics({"../outside.md": []}, tmp_path)
    with pytest.raises(ValePayloadError):
        parse_diagnostics({"README.md": {"not": "an array"}}, tmp_path)


def test_parse_metrics_aggregates_flat_and_per_file_values() -> None:
    metrics = parse_metrics(
        {
            "README.md": {"words": 40, "sentences": 2},
            "guide.md": {"words": 60, "sentences": 3},
            "paragraphs": 2,
        }
    )
    assert metrics == {"words": 100.0, "sentences": 5.0, "paragraphs": 2.0}
    with pytest.raises(ValePayloadError):
        parse_metrics(["not", "a", "mapping"])


def test_batching_is_deterministic_and_bounded() -> None:
    batches = batch_documentation_files(
        ["docs/z.md", "README.md", "docs/a.md"],
        config_path=ROOT / "config" / "analyzers" / "vale" / ".vale.ini",
        max_files=2,
        max_command_bytes=1000,
    )
    assert batches == (("README.md", "docs/a.md"), ("docs/z.md",))


def test_clean_documentation_produces_pass_and_docs_score(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(
        _output(json.dumps({})),
        _output(json.dumps({"words": 100, "sentences": 4, "paragraphs": 1})),
    )

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.PASS
    assert result.score == pytest.approx(50.0)
    assert result.score_dimension == "docs"
    assert result.available_weight == 1
    assert result.total_weight == 1
    assert result.findings == ()
    assert _metric(result, "vale_quality").denominator == 1
    assert result.diagnostics["coverage"] == 1.0
    assert result.diagnostics["threshold_exit_count"] == 0
    assert len(process.requests) == 2
    assert process.requests[0].args[0].startswith("--config=")
    assert process.requests[0].args[1] == "--output=JSON"
    assert process.requests[1].args[0] == "ls-metrics"


def test_warnings_and_errors_are_findings_with_bounded_density_score(tmp_path: Path) -> None:
    _write_readme(tmp_path, "AWS-shaped sourcecraft wording.")
    diagnostics = {
        "README.md": [
            _diagnostic(
                check="RepoHealth.Clarity",
                severity="warning",
                message="Use precise wording.",
                line=1,
                match="AWS-shaped",
            ),
            _diagnostic(
                check="RepoHealth.Terminology",
                severity="error",
                message="Use SourceCraft.",
                line=1,
                match="sourcecraft",
            ),
        ]
    }
    process = FakeProcess(
        _output(json.dumps(diagnostics), exit_code=1),
        _output(json.dumps({"words": 100, "sentences": 4})),
    )

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.FAIL
    assert len(result.findings) == 2
    assert result.score is not None and 0 < result.score < 100
    assert result.diagnostics["threshold_exit_count"] == 1
    assert result.diagnostics["threshold_exit_codes"] == [1]
    assert result.diagnostics["weighted_finding_points"] == pytest.approx(3.0)
    assert "AWS-shaped" not in result.model_dump_json()
    assert result.findings[0].evidence_refs[0].snippet_hash
    assert result.raw_payload_ref and result.raw_payload_ref.startswith("vale://")


def test_missing_vale_is_skipped_and_does_not_invoke_process(tmp_path: Path, monkeypatch) -> None:
    _write_readme(tmp_path)
    process = FakeProcess()
    monkeypatch.setattr(vale_module.shutil, "which", lambda _name: None)

    result = ValeAdapter(process=process, project_root=ROOT).run(
        _context(tmp_path, vale_available=False)
    )

    assert result.status is AnalyzerStatus.SKIPPED
    assert result.limitations[0].kind == "missing_capability"
    assert result.diagnostics["failure_kind"] == "vale_missing"
    assert result.diagnostics["process_invoked"] is False
    assert result.diagnostics["coverage"] == 0.0
    assert result.diagnostics["confidence"] == 0.0
    assert process.requests == []


def test_malformed_diagnostics_json_is_an_error(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(_output("{not-json"))

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert result.score is None
    assert result.limitations[0].kind == "error"
    assert result.diagnostics["failure_kind"] == "error"
    assert result.diagnostics["coverage"] == 0.0
    assert result.diagnostics["confidence"] == 0.0
    assert result.raw_payload_ref and result.raw_payload_ref.startswith("vale://")


def test_malformed_metrics_json_is_an_error(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(_output(json.dumps({})), _output("{not-json"))

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert result.score is None
    assert result.limitations[0].kind == "error"
    assert result.diagnostics["failed_batches"][0]["phase"] == "metrics"


def test_process_start_error_is_error_and_not_missing_vale(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(_output("", exit_code=None, start_error=OSError("permission denied")))

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert result.limitations[0].kind == "error"
    assert result.diagnostics["failure_kind"] == "error"
    assert result.diagnostics["failed_batches"][0]["kind"] == "error"


def test_empty_metrics_object_is_a_usable_metrics_result(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(_output(json.dumps({})), _output(json.dumps({})))

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.PASS
    assert result.diagnostics["metrics_coverage"] == 1.0
    assert result.diagnostics["analyzed_files"] == 1


def test_partial_metrics_failure_preserves_coverage_and_marks_warning(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    (tmp_path / "guide.md").write_text("A second guide.", encoding="utf-8")
    process = FakeProcess(
        _output(json.dumps({})),
        _output(json.dumps({"words": 50})),
        _output("{not-json"),
    )

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.WARN
    assert result.diagnostics["coverage"] == 0.5
    assert result.diagnostics["metrics_coverage"] == 0.5
    assert result.diagnostics["confidence"] == 0.5
    assert result.diagnostics["analyzed_files"] == 1
    assert result.limitations[0].kind == "error"
    assert result.diagnostics["failed_batches"][0]["file"] == "guide.md"


def test_finding_penalty_is_capped_and_word_volume_does_not_change_source_weight(
    tmp_path: Path,
) -> None:
    _write_readme(tmp_path)
    diagnostics = {
        "README.md": [
            _diagnostic(
                check="RepoHealth.Clarity",
                severity="error",
                message="Use precise wording.",
                line=index + 1,
                match="bad",
            )
            for index in range(200)
        ]
    }
    first = ValeAdapter(
        process=FakeProcess(
            _output(json.dumps(diagnostics)),
            _output(json.dumps({"words": 20})),
        ),
        project_root=ROOT,
    ).run(_context(tmp_path))
    second = ValeAdapter(
        process=FakeProcess(
            _output(json.dumps(diagnostics)),
            _output(json.dumps({"words": 20000})),
        ),
        project_root=ROOT,
    ).run(_context(tmp_path))

    assert first.score == pytest.approx(25.0)
    assert second.score == first.score
    assert _metric(first, "vale_quality").denominator == 1
    assert _metric(second, "vale_quality").denominator == 1
    assert _metric(first, "vale_quality").population == _metric(second, "vale_quality").population


def test_timeout_is_distinguished_from_bad_documentation(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(_output("", exit_code=None, timed_out=True))

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert result.limitations[0].kind == "timeout"
    assert result.diagnostics["failure_kind"] == "timeout"
    assert result.score is None


def test_no_documentation_is_inconclusive_without_process_invocation(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("print('code')\n", encoding="utf-8")
    process = FakeProcess()

    result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    assert result.status is AnalyzerStatus.INCONCLUSIVE
    assert result.limitations[0].kind == "insufficient_denominator"
    assert result.diagnostics["failure_kind"] == "no_documentation"
    assert result.diagnostics["process_invoked"] is False
    assert result.diagnostics["coverage"] == 0.0
    assert result.diagnostics["confidence"] == 0.0
    assert process.requests == []


def test_result_round_trips_and_policy_version_changes_cache_identity(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(
        _output(json.dumps({})),
        _output(json.dumps({"words": 50})),
    )
    context = _context(tmp_path)
    result = ValeAdapter(process=process, project_root=ROOT).run(context)
    restored = AnalyzerResult.model_validate_json(result.model_dump_json())

    assert restored == result
    changed = VALE_DEFINITION.model_copy(update={"version": f"{VALE_DEFINITION.version}-changed"})
    assert cache_key(VALE_DEFINITION, context) != cache_key(changed, context)
    assert result.source_versions["vale_source_commit"] == VALE_SOURCE_COMMIT


def test_vale_is_registered_and_composes_with_existing_docs_source(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    process = FakeProcess(
        _output(json.dumps({})),
        _output(json.dumps({"words": 50})),
    )
    vale_result = ValeAdapter(process=process, project_root=ROOT).run(_context(tmp_path))

    registry = AnalyzerRegistry()
    register_vale_adapter(registry)
    registered = registry.get(VALE_ANALYZER_ID)
    assert registered is not None
    assert registered[0] == VALE_DEFINITION

    evidence = vale_result.evidence[0]
    baseline = AnalyzerResult(
        analyzer_id="repohealth.baseline",
        analyzer_version="baseline",
        status=AnalyzerStatus.PASS,
        score=80,
        score_dimension="docs",
        evidence=(evidence,),
        available_weight=1,
        total_weight=1,
    )
    composed = compose_health_score((baseline, vale_result))

    assert composed.dimensions["docs"] == pytest.approx(65.0)
    assert {row["analyzer_id"] for row in composed.breakdown} == {
        "repohealth.baseline",
        VALE_ANALYZER_ID,
    }


def test_discovery_excludes_binary_and_generated_documentation(tmp_path: Path) -> None:
    _write_readme(tmp_path)
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "generated.md").write_text("generated", encoding="utf-8")
    (tmp_path / "binary.md").write_bytes(b"text\0binary")
    policy = load_vale_policy(ROOT)

    assert discover_documentation_files(tmp_path, policy) == ("README.md",)


def test_definition_contract_remains_explicit() -> None:
    expected = AnalyzerDefinition.model_validate(VALE_DEFINITION.model_dump())
    assert expected.id == VALE_ANALYZER_ID
    assert expected.source_commit == VALE_SOURCE_COMMIT
    assert expected.requires == ("local_scan",)
