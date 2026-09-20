"""Contract and normalization tests for the SourceCraft CI/CD boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext  # noqa: E402
from repowise.core.analysis.health.integrations.cicd_adapter import (  # noqa: E402
    SourceCraftCICDAdapter,
)
from repowise.core.analysis.health.integrations.cicd_facts import (  # noqa: E402
    CICDDataStatus,
    CICDRunStatus,
    load_cicd_policy,
    percentile,
)

ROOT = Path(__file__).resolve().parents[3]
AS_OF = datetime(2026, 9, 19, tzinfo=UTC)


def teardown_module() -> None:
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _fixture(name: str) -> dict:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "cicd" / f"{name}.json").read_text(encoding="utf-8")
    )


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=ROOT,
        repo_id="fixture/cicd",
        head_sha="fixture-head",
        as_of_ts=AS_OF,
        mode="offline",
        inventory={"sourcecraft_cicd": inventory},
    )


def test_policy_is_versioned_and_has_concrete_windows() -> None:
    policy = load_cicd_policy(ROOT)

    assert policy.analysis_window_days == 90
    assert (policy.current_period_days, policy.previous_period_days) == (30, 30)
    assert policy.p50_target_seconds == 300
    assert policy.p95_breach_seconds == 3600
    assert len(policy.digest) == 64


def test_no_ci_and_configured_no_runs_are_distinct() -> None:
    adapter = SourceCraftCICDAdapter()

    no_ci = adapter.collect(_context(_fixture("no_ci")), load_cicd_policy(ROOT))
    no_runs = adapter.collect(_context(_fixture("configured_no_runs")), load_cicd_policy(ROOT))

    assert no_ci.status is CICDDataStatus.CI_NOT_CONFIGURED
    assert no_ci.configured is False
    assert no_runs.status is CICDDataStatus.NO_RUNS
    assert no_runs.configured is True


def test_missing_inventory_and_api_unavailable_are_not_negative_runs() -> None:
    adapter = SourceCraftCICDAdapter()
    missing = adapter.collect(
        _context({}),
        load_cicd_policy(ROOT),
    )
    unavailable = adapter.collect(
        _context(_fixture("unavailable")),
        load_cicd_policy(ROOT),
    )

    assert missing.status is CICDDataStatus.UNAVAILABLE
    assert unavailable.status is CICDDataStatus.UNAVAILABLE
    assert missing.runs == unavailable.runs == ()


def test_mixed_statuses_keep_rejected_separate_and_exclude_unknown_from_rates() -> None:
    facts = SourceCraftCICDAdapter().collect(
        _context(_fixture("mixed_statuses")),
        load_cicd_policy(ROOT),
    )

    assert facts.status is CICDDataStatus.MEASURED
    assert sum(run.status is CICDRunStatus.REJECTED for run in facts.runs) == 1
    assert sum(run.status is CICDRunStatus.CANCELLED for run in facts.runs) == 1
    assert facts.unknown_status_count == 1
    assert facts.latest_terminal is not None
    assert facts.latest_terminal.status is CICDRunStatus.FAILURE


def test_duplicate_refs_are_deduplicated_with_deterministic_winner() -> None:
    payload = _fixture("all_success")
    payload["runs"] = [
        payload["runs"][0],
        {
            **payload["runs"][0],
            "updated_at": "2026-09-10T10:00:00Z",
            "duration_seconds": 999,
        },
        *payload["runs"][1:],
    ]

    first = SourceCraftCICDAdapter().collect(_context(payload), load_cicd_policy(ROOT))
    second = SourceCraftCICDAdapter().collect(
        _context(dict(reversed(list(payload.items())))), load_cicd_policy(ROOT)
    )

    assert first.duplicate_record_count == 1
    assert len(first.runs) == 6
    selected = next(run for run in first.runs if run.run_id == "s1")
    assert selected.duration_seconds == 999
    assert first.summary() == second.summary()


def test_partial_pagination_lowers_coverage_and_status() -> None:
    facts = SourceCraftCICDAdapter().collect(
        _context(_fixture("partial_pagination")),
        load_cicd_policy(ROOT),
    )

    assert facts.status is CICDDataStatus.PARTIAL
    assert facts.pagination_complete is False
    assert facts.coverage < 1.0
    assert "pagination_incomplete" in facts.limitations


def test_malformed_pagination_is_partial_without_failed_runs() -> None:
    payload = _fixture("all_success")
    payload["pagination"] = ["malformed-pagination-metadata"]

    facts = SourceCraftCICDAdapter().collect(
        _context(payload),
        load_cicd_policy(ROOT),
    )

    assert facts.status is CICDDataStatus.PARTIAL
    assert facts.pagination_complete is None
    assert facts.runs
    assert all(run.status is CICDRunStatus.SUCCESS for run in facts.runs)
    assert "pagination_incomplete" in facts.limitations


def test_malformed_rows_and_schema_are_safe() -> None:
    adapter = SourceCraftCICDAdapter()
    malformed_rows = adapter.collect(
        _context(_fixture("malformed_rows")),
        load_cicd_policy(ROOT),
    )
    bad_schema = _fixture("all_success")
    bad_schema["schema_version"] = "sourcecraft-cicd-inventory-v999"
    invalid = adapter.collect(_context(bad_schema), load_cicd_policy(ROOT))

    assert malformed_rows.malformed_record_count == 2
    assert malformed_rows.runs[0].run_id == "valid"
    assert invalid.status is CICDDataStatus.ERROR
    with pytest.raises(json.JSONDecodeError):
        json.loads((ROOT / "tests" / "fixtures" / "cicd" / "malformed_payload.json").read_text())


def test_retry_relation_requires_explicit_group_and_matching_workflow_commit() -> None:
    facts = SourceCraftCICDAdapter().collect(
        _context(_fixture("retry_flaky")),
        load_cicd_policy(ROOT),
    )

    assert facts.retry_detection_status == "MEASURED"
    assert len(facts.retry_relations) == 1
    assert facts.retry_relations[0].failed_run_id == "r1"
    assert facts.retry_relations[0].successful_run_id == "r2"


def test_terminal_without_finish_is_not_a_terminal_sample() -> None:
    payload = _fixture("all_success")
    payload["runs"] = [
        {
            "id": "incomplete",
            "status": "success",
            "updated_at": "2026-09-10T10:00:00Z",
        }
    ]
    facts = SourceCraftCICDAdapter().collect(_context(payload), load_cicd_policy(ROOT))

    assert facts.status is CICDDataStatus.INSUFFICIENT_HISTORY
    assert facts.terminal_runs == ()
    assert facts.latest_terminal is None
    assert "terminal_runs_missing_finished_at" in facts.limitations


def test_sourcecraft_nested_dates_and_workflows_are_normalized() -> None:
    payload = _fixture("all_success")
    sourcecraft_row = payload["runs"][0]
    payload["runs"] = [
        {
            "id": sourcecraft_row["id"],
            "status": sourcecraft_row["status"],
            "dates": {
                "created_at": sourcecraft_row["created_at"],
                "started_at": sourcecraft_row["started_at"],
                "finished_at": sourcecraft_row["finished_at"],
                "updated_at": sourcecraft_row["updated_at"],
            },
            "workflows": [
                {
                    "id": "workflow-1",
                    "slug": "build",
                    "tasks": [{"id": "task-1"}],
                }
            ],
        }
    ]

    facts = SourceCraftCICDAdapter().collect(
        _context(payload),
        load_cicd_policy(ROOT),
    )

    assert facts.runs[0].finished_at is not None
    assert facts.runs[0].workflow_id == "workflow-1"
    assert facts.runs[0].workflow_name == "build"
    assert facts.runs[0].task_ids == ("task-1",)


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([], 0.5) is None
    assert percentile([10], 0.95) == 10
    assert percentile([1, 2], 0.75) == pytest.approx(1.75)
    assert percentile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
