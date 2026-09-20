from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.unit.health.issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from scripts.verify_cicd_fixture import _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
AS_OF = datetime(2026, 9, 19, tzinfo=UTC)


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def test_verification_report_preserves_operational_run_and_source_summary() -> None:
    envelope = json.loads(
        (ROOT / "tests" / "fixtures" / "cicd" / "failure_streak.json").read_text(encoding="utf-8")
    )

    report = _run(envelope, ROOT, AS_OF)

    assert report["runs"]["latest_run"]["run_id"] == "f6"
    assert report["runs"]["last_successful_run"]["run_id"] == "f1"
    assert report["runs"]["last_run_status"] == "FAILURE"
    assert report["runs"]["failure_streak"] == 5
    assert report["source"]["version"] == envelope["source_version"]
    assert report["source"]["raw_records"] == 6
    assert report["source"]["deduplicated_records"] == 6
    assert report["source"]["out_of_window_count"] == 0
    assert report["source"]["timeout_count"] == 0
