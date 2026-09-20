"""Deterministic normalization and policy tests for Issues facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext

from .issues_test_support import (
    install_preexisting_coverage_shim,
    restore_preexisting_coverage_shim,
)

_PREVIOUS_COVERAGE = install_preexisting_coverage_shim()

from repowise.core.analysis.health.integrations.issues_facts import (  # noqa: E402
    ActorClass,
    IssueMetricStatus,
    IssueState,
    classify_actor,
    load_issues_policy,
    normalize_issue_inventory,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "issues"
AS_OF = datetime(2026, 9, 10, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def _restore_coverage_shim():
    yield
    restore_preexisting_coverage_shim(_PREVIOUS_COVERAGE)


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=ROOT,
        repo_id="fixture/issues",
        head_sha="fixture-head",
        as_of_ts=AS_OF,
        mode="offline",
        inventory=inventory,
        capabilities=("chaoss:events",),
    )


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_policy_is_versioned_and_loaded_from_repository_config() -> None:
    policy = load_issues_policy(ROOT)

    assert policy.policy_revision == "issues-sourcecraft-policy-v1"
    assert policy.analysis_window_days == 90
    assert policy.stale_threshold_days == 30
    assert policy.minimum_sample == 5
    assert policy.digest
    assert policy.response_median_target_hours < policy.response_median_breach_hours


def test_rich_source_normalizes_facts_redacts_actors_and_deduplicates() -> None:
    facts = normalize_issue_inventory(_context(_fixture("rich.json")), load_issues_policy(ROOT))

    assert facts.status is IssueMetricStatus.MEASURED
    assert [issue.issue_id for issue in facts.issues] == ["101", "102", "103", "104", "105", "106"]
    assert facts.records_observed == 8
    assert facts.duplicate_record_count == 1
    assert facts.excluded_pull_request_count == 1
    assert facts.comments_available is True
    assert facts.state_events_available is True
    assert facts.coverage >= 0.8
    assert all(not hasattr(event, "body") for issue in facts.issues for event in issue.events)
    assert all(event.actor_key is None or len(event.actor_key) == 24 for issue in facts.issues for event in issue.events)

    reopened = next(issue for issue in facts.issues if issue.issue_id == "103")
    assert any(event.event_type.value == "reopened" for event in reopened.events)
    assert reopened.state is IssueState.CLOSED


def test_sourcecraft_completed_at_is_normalized_as_closed_at() -> None:
    inventory = {
        "records_available": True,
        "pagination_complete": True,
        "local_date_filter_applied": True,
        "comments_available": True,
        "issues": [
            {
                "id": "sourcecraft-completed",
                "created_at": "2026-09-01T00:00:00Z",
                "completed_at": "2026-09-02T00:00:00Z",
                "state": "closed",
            }
        ],
        "issue_comments": [],
    }

    facts = normalize_issue_inventory(_context(inventory), load_issues_policy(ROOT))

    assert facts.issues[0].closed_at == datetime(2026, 9, 2, tzinfo=UTC)
    assert facts.issues[0].state is IssueState.CLOSED


def test_nested_sourcecraft_status_slug_is_normalized() -> None:
    inventory = {
        "records_available": True,
        "pagination_complete": True,
        "local_date_filter_applied": True,
        "comments_available": True,
        "issues": [
            {
                "id": "sourcecraft-open",
                "created_at": "2026-09-01T00:00:00Z",
                "status": {"slug": "open", "name": "Open"},
            }
        ],
        "issue_comments": [],
    }

    facts = normalize_issue_inventory(_context(inventory), load_issues_policy(ROOT))

    assert facts.issues[0].state is IssueState.OPEN


def test_actor_policy_handles_bot_human_and_unknown_without_raw_login_contract() -> None:
    policy = load_issues_policy(ROOT)

    bot, bot_reason, bot_identity = classify_actor({"login": "dependabot[bot]"}, policy)
    human, human_reason, human_identity = classify_actor({"login": "maintainer", "is_bot": False}, policy)
    unknown, unknown_reason, unknown_identity = classify_actor({}, policy)

    assert (bot, bot_reason, bot_identity) == (ActorClass.BOT, "known_identity", "dependabot[bot]")
    assert (human, human_reason, human_identity) == (ActorClass.HUMAN, "explicit_marker", "maintainer")
    assert (unknown, unknown_reason, unknown_identity) == (ActorClass.UNKNOWN, "unknown", None)


def test_missing_granular_source_is_unavailable_not_empty() -> None:
    inventory = {
        "chaoss_rows": {
            "issues_first_time_opened": [{"value": 4}],
            "pull_requests_new": [{"value": 2}],
        }
    }

    facts = normalize_issue_inventory(_context(inventory), load_issues_policy(ROOT))

    assert facts.status is IssueMetricStatus.UNAVAILABLE
    assert facts.issues == ()
    assert "granular" in facts.limitations[0].lower()


def test_complete_empty_source_is_no_issues() -> None:
    facts = normalize_issue_inventory(_context(_fixture("no_issues.json")), load_issues_policy(ROOT))

    assert facts.status is IssueMetricStatus.NO_ISSUES
    assert facts.issue_records_available is True
    assert facts.issues == ()


def test_empty_incomplete_source_is_partial_not_no_issues() -> None:
    inventory = {
        "records_available": True,
        "records_expected": 3,
        "pagination_complete": False,
        "local_date_filter_applied": True,
        "issues": [],
    }

    facts = normalize_issue_inventory(_context(inventory), load_issues_policy(ROOT))

    assert facts.status is IssueMetricStatus.PARTIAL
    assert facts.issues == ()
    assert "pagination" in " ".join(facts.limitations).lower()


def test_malformed_rows_are_bounded_and_do_not_become_issue_zeroes() -> None:
    inventory = {
        "source_version": "sourcecraft-test",
        "records_available": True,
        "pagination_complete": True,
        "local_date_filter_applied": True,
        "issues": [{"id": "bad", "created_at": "not-a-date"}, "not-a-mapping"],
    }

    facts = normalize_issue_inventory(_context(inventory), load_issues_policy(ROOT))

    assert facts.status is IssueMetricStatus.PARTIAL
    assert [issue.issue_id for issue in facts.issues] == ["bad"]
    assert facts.malformed_record_count == 2
