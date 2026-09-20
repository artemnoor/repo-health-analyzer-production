"""SourceCraft AppSec adapter contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.health.integrations.appsec_adapter import (  # noqa: E402
    AppSecDataStatus,
    AppSecPayloadError,
    SourceCraftAppSecAdapter,
    normalize_appsec_payload,
)
from repowise.core.analysis.health.integrations.contracts import AnalyzerContext  # noqa: E402


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


def test_normalizes_active_and_fixed_findings_without_provider_objects() -> None:
    facts = normalize_appsec_payload(
        {
            "scans": [{"uuid": "scan-1"}],
            "groups": [
                {"uuid": "group-active", "engine": "gitleaks", "ruleName": "secret", "severity": "critical", "status": 0},
                {"uuid": "group-fixed", "engine": "sast", "ruleName": "old", "severity": "high", "status": 9},
            ],
            "findings": [
                {"uuid": "finding-1", "groupUuid": "group-active", "fileName": "src/app.py", "line": 7},
                {"uuid": "finding-fixed", "groupUuid": "group-fixed", "fileName": "src/old.py", "line": 3},
            ],
        },
        repository_id="repo-1",
    )

    assert facts.status is AppSecDataStatus.MEASURED
    assert len(facts.active_findings) == 1
    assert facts.active_findings[0].severity == "critical"
    assert facts.active_findings[0].file == "src/app.py"
    assert facts.active_findings[0].line == 7


def test_unknown_provider_status_and_severity_are_explicit() -> None:
    facts = normalize_appsec_payload(
        {
            "scans": [{"uuid": "scan-1"}],
            "groups": [{"uuid": "group-1", "status": 42, "severity": "new-provider-value"}],
            "findings": [{"uuid": "finding-1", "groupUuid": "group-1"}],
        }
    )

    assert facts.findings[0].state == "UNKNOWN"
    assert facts.findings[0].severity == "unknown"
    assert facts.diagnostics["unknown_severity_count"] == 1


def test_missing_repository_id_is_unavailable_without_transport_call() -> None:
    adapter = SourceCraftAppSecAdapter(transport=None)
    facts = adapter.collect(
        AnalyzerContext(
            repo_path=Path("."),
            repo_id="fixture",
            head_sha="head",
            as_of_ts=datetime(2026, 9, 20, tzinfo=UTC),
            inventory={},
        )
    )

    assert facts.status is AppSecDataStatus.UNAVAILABLE
    assert facts.failure_kind == "repository_id_missing"


def test_malformed_provider_shape_is_rejected() -> None:
    import pytest

    with pytest.raises(AppSecPayloadError):
        normalize_appsec_payload({"scans": {"not": "an-array"}, "groups": [], "findings": []})
