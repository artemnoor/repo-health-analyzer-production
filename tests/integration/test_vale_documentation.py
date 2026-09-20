"""In-process integration of Vale with the existing documentation source."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
)
from repowise.core.analysis.analyzer_integration.process import ProcessOutput

ROOT = Path(__file__).resolve().parents[2]

from repowise.core.analysis.health.integrations.contracts import (  # noqa: E402
    EvidenceRef,
)
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry  # noqa: E402
from repowise.core.analysis.health.integrations.vale_adapter import (  # noqa: E402
    VALE_ANALYZER_ID,
    VALE_DEFINITION,
    ValeAdapter,
    register_vale_adapter,
)


class FakeProcess:
    def __init__(self, *outputs: ProcessOutput) -> None:
        self.outputs = list(outputs)

    def run(self, _request: Any) -> ProcessOutput:
        return self.outputs.pop(0)


def _output(stdout: str, *, exit_code: int | None = 0) -> ProcessOutput:
    return ProcessOutput(
        tool_id=VALE_ANALYZER_ID,
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_ms=1,
    )


def _context(repo: Path, *, vale_available: bool = True) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=repo,
        repo_id="vale-integration",
        head_sha="integration-head",
        as_of_ts=datetime(2026, 9, 18, tzinfo=UTC),
        capabilities=("local_scan",),
        tool_paths={"vale": sys.executable} if vale_available else {},
    )


def _baseline(evidence: EvidenceRef) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id="repohealth.baseline",
        analyzer_version="baseline",
        status=AnalyzerStatus.WARN,
        score=60,
        score_dimension="docs",
        evidence=(evidence,),
        available_weight=1,
        total_weight=1,
    )


def _compose(results: tuple[AnalyzerResult, ...], repository_id: str):
    from repowise.core.analysis.health.composite import compose_health_score

    return compose_health_score(results, repository_id=repository_id)


def test_registered_vale_result_is_additive_to_baseline(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("A clean README.", encoding="utf-8")
    process = FakeProcess(_output(json.dumps({})), _output(json.dumps({"words": 40})))
    context = _context(tmp_path)
    vale = ValeAdapter(process=process, project_root=ROOT).run(context)

    registry = AnalyzerRegistry()
    register_vale_adapter(registry)
    assert registry.get(VALE_ANALYZER_ID) is not None
    assert registry.get(VALE_ANALYZER_ID)[0] == VALE_DEFINITION  # type: ignore[index]

    baseline = _baseline(vale.evidence[0])
    composed = _compose((baseline, vale), context.repo_id)

    # The v2 documentation score includes completeness and executable
    # instructions, so a README-only clean prose sample scores 50.  Vale
    # remains additive to the legacy baseline: (60 + 50) / 2 = 55.
    assert composed.dimensions["docs"] == pytest.approx(55.0)
    assert {row["analyzer_id"] for row in composed.breakdown} == {
        "repohealth.baseline",
        VALE_ANALYZER_ID,
    }
    assert all(row["dimension"] == "docs" for row in composed.breakdown)


def test_missing_vale_keeps_baseline_docs_evidence(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("A README.", encoding="utf-8")
    import importlib

    vale_module = importlib.import_module("repowise.core.analysis.health.integrations.vale_adapter")
    monkeypatch.setattr(vale_module.shutil, "which", lambda _name: None)
    vale = ValeAdapter(process=FakeProcess(), project_root=ROOT).run(
        _context(tmp_path, vale_available=False)
    )

    baseline = _baseline(
        EvidenceRef(source="repohealth.baseline", collected_at=datetime(2026, 9, 18, tzinfo=UTC))
    )
    composed = _compose((baseline, vale), "vale-integration")

    assert vale.status is AnalyzerStatus.SKIPPED
    assert vale.limitations[0].kind == "missing_capability"
    assert composed.dimensions["docs"] == pytest.approx(60.0)
    assert (
        any(
            limitation.kind == "missing_capability" and limitation.affected_scope == "docs"
            for limitation in composed.limitations
        )
        is False
    )


def test_valid_threshold_findings_remain_content_status_not_process_error(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("AWS-shaped wording.", encoding="utf-8")
    diagnostics = {
        "README.md": [
            {
                "Check": "RepoHealth.Clarity",
                "Severity": "warning",
                "Message": "Use precise wording.",
                "Line": 1,
                "Match": "AWS-shaped",
            }
        ]
    }
    vale = ValeAdapter(
        process=FakeProcess(
            _output(json.dumps(diagnostics), exit_code=1),
            _output(json.dumps({"words": 30})),
        ),
        project_root=ROOT,
    ).run(_context(tmp_path))

    assert vale.status is AnalyzerStatus.WARN
    assert vale.limitations == ()
    assert vale.diagnostics["threshold_exit_count"] == 1
