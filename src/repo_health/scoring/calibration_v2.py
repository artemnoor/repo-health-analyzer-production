"""Pure calibration-v2 policies used by the six category analyzers.

The functions in this module are deliberately independent from collection,
FastAPI, persistence and provider SDKs.  They are the source-to-source port of
the proven calibration policy so the extraction changes boundaries, not
scoring semantics.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import pairwise

CALIBRATION_V2_VERSION = "repo-health-calibration-v2"
DOCUMENTATION_POLICY_REVISION = "documentation-calibration-v2"
ACTIVITY_POLICY_REVISION = "activity-calibration-v2"
CICD_POLICY_REVISION = "cicd-calibration-v2"
ISSUES_POLICY_REVISION = "issues-calibration-v2"
CODE_HEALTH_POLICY_REVISION = "code-health-calibration-v2"
SECURITY_POLICY_REVISION = "security-appsec-v1"

DOCUMENTATION_FINDING_PENALTY = 10.0
DOCUMENTATION_FINDING_DENSITY_SCALE = 600.0
DOCUMENTATION_FINDING_MIN_WORDS = 500.0

DOCUMENTATION_WEIGHTS = {
    "completeness": 0.40,
    "instructions": 0.20,
    "vale_quality": 0.25,
    "readability": 0.15,
}
ACTIVITY_WEIGHTS = {
    "history": 0.25,
    "cadence": 0.25,
    "recency": 0.35,
    "breadth": 0.15,
}
CICD_WEIGHTS = {
    "reliability": 0.75,
    "failure_streak": 0.15,
    "duration": 0.05,
    "trend": 0.05,
}
RELIABILITY_ANCHORS = (
    (0.0, 100.0),
    (5.0, 95.0),
    (10.0, 90.0),
    (20.0, 80.0),
    (30.0, 70.0),
    (50.0, 50.0),
    (100.0, 0.0),
)
DURATION_ANCHORS = (
    (0.0, 100.0),
    (300.0, 100.0),
    (900.0, 70.0),
    (1800.0, 30.0),
    (3600.0, 0.0),
)


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, float(value)))


def ratio(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def anchored_quality(value: float, anchors: Iterable[tuple[float, float]]) -> float:
    points = tuple(anchors)
    if not points:
        return 0.0
    if value <= points[0][0]:
        return points[0][1]
    for (left_x, left_y), (right_x, right_y) in pairwise(points):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    return points[-1][1]


def documentation_score(*, completeness: float, instructions: float, vale_quality: float, readability: float) -> float:
    return clamp(
        DOCUMENTATION_WEIGHTS["completeness"] * clamp(completeness)
        + DOCUMENTATION_WEIGHTS["instructions"] * clamp(instructions)
        + DOCUMENTATION_WEIGHTS["vale_quality"] * clamp(vale_quality)
        + DOCUMENTATION_WEIGHTS["readability"] * clamp(readability)
    )


def documentation_quality(*, finding_points: float, words: float) -> tuple[float, float]:
    """Return Vale quality and bounded finding density."""
    safe_words = max(0.0, float(words))
    denominator = max(safe_words, DOCUMENTATION_FINDING_MIN_WORDS)
    density = max(0.0, float(finding_points)) / denominator
    penalty = min(
        100.0,
        max(0.0, float(finding_points)) * DOCUMENTATION_FINDING_PENALTY
        + max(0.0, float(finding_points))
        / max(safe_words, DOCUMENTATION_FINDING_MIN_WORDS)
        * DOCUMENTATION_FINDING_DENSITY_SCALE,
    )
    return clamp(100.0 - penalty), density


def activity_score(
    *,
    unique_commits: float,
    latest_age_days: float | None,
    meaningful_ratio: float | None,
    commits_90d: float,
    authors_90d: float,
    empty_commits: float,
) -> tuple[float, dict[str, float]]:
    history = min(1.0, math.log1p(max(0.0, unique_commits)) / math.log1p(50.0))
    cadence = min(1.0, max(0.0, commits_90d) / 8.0)
    recency = math.exp(-max(0.0, latest_age_days if latest_age_days is not None else 365.0) / 45.0)
    breadth = min(1.0, max(0.0, authors_90d) / 4.0)
    empty_ratio = min(1.0, max(0.0, empty_commits) / max(unique_commits, 1.0))
    meaningful = ratio(meaningful_ratio)
    integrity = max(0.0, min(1.0, 0.70 * meaningful + 0.30 * (1.0 - empty_ratio)))
    raw = (
        ACTIVITY_WEIGHTS["history"] * history
        + ACTIVITY_WEIGHTS["cadence"] * cadence
        + ACTIVITY_WEIGHTS["recency"] * recency
        + ACTIVITY_WEIGHTS["breadth"] * breadth
    )
    score = clamp(100.0 * raw * (0.25 + 0.75 * integrity))
    return score, {
        "history": history,
        "cadence": cadence,
        "recency": recency,
        "breadth": breadth,
        "meaningful": meaningful,
        "empty_ratio": empty_ratio,
        "integrity": integrity,
        "raw": 100.0 * raw,
    }


def cicd_component_score(
    *,
    failure_rate: float | None,
    failure_streak: int,
    p50_seconds: float | None,
    p95_seconds: float | None,
    failure_rate_delta: float | None,
    duration_delta: float | None = None,
    available_components: set[str] | None = None,
) -> tuple[float | None, dict[str, float], set[str]]:
    components: dict[str, float] = {}
    if failure_rate is not None:
        components["reliability"] = anchored_quality(ratio(failure_rate) * 100.0, RELIABILITY_ANCHORS)
        components["failure_streak"] = 100.0 * math.exp(-max(0, int(failure_streak)) / 3.0)
    if p50_seconds is not None and p95_seconds is not None:
        components["duration"] = (
            anchored_quality(max(0.0, p50_seconds), DURATION_ANCHORS)
            + anchored_quality(max(0.0, p95_seconds), DURATION_ANCHORS)
        ) / 2.0
    if failure_rate_delta is not None:
        trend_signal = failure_rate_delta / 0.20
        if duration_delta is not None:
            trend_signal = 0.70 * trend_signal + 0.30 * duration_delta / 0.50
        components["trend"] = clamp(100.0 - 100.0 * trend_signal)
    if available_components is not None:
        components = {name: value for name, value in components.items() if name in available_components}
    eligible = set(components)
    if len(eligible) < 2 or not {"reliability", "failure_streak"} & eligible:
        return None, components, eligible
    total = sum(CICD_WEIGHTS[name] for name in eligible)
    score = sum(CICD_WEIGHTS[name] * value for name, value in components.items()) / total
    return clamp(score), components, eligible


__all__ = [
    "ACTIVITY_POLICY_REVISION",
    "ACTIVITY_WEIGHTS",
    "CALIBRATION_V2_VERSION",
    "CICD_POLICY_REVISION",
    "CICD_WEIGHTS",
    "CODE_HEALTH_POLICY_REVISION",
    "DOCUMENTATION_FINDING_DENSITY_SCALE",
    "DOCUMENTATION_FINDING_MIN_WORDS",
    "DOCUMENTATION_FINDING_PENALTY",
    "DOCUMENTATION_POLICY_REVISION",
    "DOCUMENTATION_WEIGHTS",
    "DURATION_ANCHORS",
    "ISSUES_POLICY_REVISION",
    "RELIABILITY_ANCHORS",
    "SECURITY_POLICY_REVISION",
    "activity_score",
    "anchored_quality",
    "cicd_component_score",
    "clamp",
    "documentation_quality",
    "documentation_score",
    "ratio",
]
