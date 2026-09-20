"""Security analyzer score/status semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.health.integrations.appsec_adapter import (  # noqa: E402
    SourceCraftAppSecAdapter,
)
from repowise.core.analysis.health.integrations.appsec_analyzer import AppSecAnalyzer  # noqa: E402
from repowise.core.analysis.health.integrations.contracts import (  # noqa: E402
    AnalyzerContext,
    AnalyzerStatus,
)


def _context(payload: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id="fixture",
        head_sha="head",
        as_of_ts=datetime(2026, 9, 20, tzinfo=UTC),
        inventory={"sourcecraft_appsec": payload, "repository_id": "repo-1"},
    )


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def test_clean_security_is_measured_and_scores_100() -> None:
    result = AppSecAnalyzer(adapter=SourceCraftAppSecAdapter()).run(_context({"scans": [{"uuid": "scan"}], "groups": [], "findings": []}))
    assert result.status is AnalyzerStatus.PASS
    assert result.score == 100
    assert result.diagnostics["security_status"] == "MEASURED"


def test_critical_security_finding_is_fail_but_not_zero_imputation() -> None:
    result = AppSecAnalyzer(adapter=SourceCraftAppSecAdapter()).run(
        _context(
            {
                "scans": [{"uuid": "scan"}],
                "groups": [{"uuid": "group", "engine": "sast", "ruleName": "r", "severity": "critical", "status": 0}],
                "findings": [{"uuid": "finding", "groupUuid": "group", "fileName": "src/app.py", "line": 4}],
            }
        )
    )
    assert result.status is AnalyzerStatus.FAIL
    assert result.score == 55
    assert result.findings[0].severity == "critical"


def test_unavailable_security_has_no_score() -> None:
    result = AppSecAnalyzer(adapter=SourceCraftAppSecAdapter()).run(_context({"status": "UNAVAILABLE", "reason": "forbidden"}))
    assert result.status is AnalyzerStatus.SKIPPED
    assert result.score is None
    assert result.diagnostics["security_status"] == "UNAVAILABLE"
