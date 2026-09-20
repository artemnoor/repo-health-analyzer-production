"""Golden checks for the shared calibration-v2 category policies."""

from __future__ import annotations

import pytest

from repowise.core.analysis.health.calibration_policy_v2 import (
    ACTIVITY_POLICY_REVISION,
    CICD_POLICY_REVISION,
    DOCUMENTATION_POLICY_REVISION,
    activity_score,
    cicd_component_score,
    documentation_score,
)


def test_policy_revisions_are_explicit_and_distinct() -> None:
    assert DOCUMENTATION_POLICY_REVISION == "documentation-calibration-v2"
    assert ACTIVITY_POLICY_REVISION == "activity-calibration-v2"
    assert CICD_POLICY_REVISION == "cicd-calibration-v2"
    assert len({DOCUMENTATION_POLICY_REVISION, ACTIVITY_POLICY_REVISION, CICD_POLICY_REVISION}) == 3


def test_documentation_fixture_golden_matches_calibration_v2() -> None:
    score = documentation_score(
        completeness=25.0,
        instructions=0.0,
        vale_quality=88.8,
        readability=51.578947368421055,
    )

    assert score == pytest.approx(39.93684210526316)


def test_activity_fixture_golden_matches_calibration_v2() -> None:
    score, components = activity_score(
        unique_commits=7.0,
        latest_age_days=4.624826388888889,
        meaningful_ratio=5.0 / 7.0,
        commits_90d=7.0,
        authors_90d=3.0,
        empty_commits=0.0,
    )

    assert score == pytest.approx(66.23917469369593)
    assert components["integrity"] == pytest.approx(0.8)


def test_cicd_fixture_golden_reweights_when_trend_is_unavailable() -> None:
    score, components, eligible = cicd_component_score(
        failure_rate=0.3125,
        failure_streak=0,
        p50_seconds=113.760477,
        p95_seconds=185.12941329999998,
        failure_rate_delta=None,
    )

    assert score == pytest.approx(75.32894736842104)
    assert eligible == {"reliability", "failure_streak", "duration"}
    assert "trend" not in components
