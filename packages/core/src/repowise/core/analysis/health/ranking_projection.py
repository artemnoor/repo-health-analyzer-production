"""Pure eligibility, normalization, and deterministic ordering for ranking."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger("health.ranking")

DEFAULT_MAX_AGE = timedelta(days=30)
DEFAULT_MIN_EVIDENCE_COVERAGE = 0.5
ALLOWED_RANKING_MODES = frozenset({"fast", "full"})
RANKING_BAND_THRESHOLDS: dict[str, float] = {
    "excellent": 90.0,
    "good": 80.0,
    "fair": 70.0,
    "weak": 60.0,
}
RANKING_BANDS = frozenset((*RANKING_BAND_THRESHOLDS, "critical", "unknown"))


@dataclass(frozen=True)
class RankingPolicy:
    """Eligibility policy kept separate from score calculation."""

    max_age: timedelta = DEFAULT_MAX_AGE
    min_evidence_coverage: float = DEFAULT_MIN_EVIDENCE_COVERAGE
    allowed_modes: frozenset[str] = ALLOWED_RANKING_MODES


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str | None = None
    stale: bool = False


@dataclass(frozen=True)
class RankingCandidate:
    """Public-safe candidate; it intentionally has no local path/raw payload."""

    repository_id: str
    name: str
    url: str
    visibility: str
    snapshot_id: str
    score_config_digest: str
    overall_score: float | None
    status: str
    dimensions: Mapping[str, float | None] = field(default_factory=dict)
    languages: tuple[str, ...] = ()
    confidence: float = 0.0
    coverage: float = 0.0
    evidence_coverage: float = 0.0
    analyzed_at: datetime | None = None
    stale_after_ts: datetime | None = None
    mode: str = "full"
    score_delta: float | None = None
    eligible: bool = False
    eligibility_reason: str | None = None


@dataclass(frozen=True)
class RankingFilter:
    band: str | None = None
    dimension: str | None = None
    language: str | None = None
    status: str | None = None
    stale: bool | None = None
    eligible: bool | None = True


def grade_for_score(score: float | None) -> str:
    if score is None or not math.isfinite(score):
        return "—"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def band_for_score(score: float | None) -> str:
    if score is None or not math.isfinite(score):
        return "unknown"
    if score >= RANKING_BAND_THRESHOLDS["excellent"]:
        return "excellent"
    if score >= RANKING_BAND_THRESHOLDS["good"]:
        return "good"
    if score >= RANKING_BAND_THRESHOLDS["fair"]:
        return "fair"
    if score >= RANKING_BAND_THRESHOLDS["weak"]:
        return "weak"
    return "critical"


def _aware(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def is_stale(candidate: RankingCandidate, *, now: datetime | None = None, policy: RankingPolicy | None = None) -> bool:
    policy = policy or RankingPolicy()
    reference = _aware(now or datetime.now(UTC))
    if candidate.analyzed_at is None:
        return True
    if reference - _aware(candidate.analyzed_at) > policy.max_age:
        return True
    return candidate.stale_after_ts is not None and _aware(candidate.stale_after_ts) <= reference


def evaluate_eligibility(
    candidate: RankingCandidate,
    *,
    now: datetime | None = None,
    policy: RankingPolicy | None = None,
) -> EligibilityDecision:
    policy = policy or RankingPolicy()
    if candidate.visibility != "public":
        return EligibilityDecision(False, "repository is not public")
    if candidate.overall_score is None or not math.isfinite(candidate.overall_score):
        return EligibilityDecision(False, "overall score is unavailable")
    if candidate.mode not in policy.allowed_modes:
        return EligibilityDecision(False, f"snapshot mode {candidate.mode!r} is not rankable")
    stale = is_stale(candidate, now=now, policy=policy)
    if stale:
        return EligibilityDecision(False, "snapshot is stale", stale=True)
    if candidate.evidence_coverage < policy.min_evidence_coverage:
        return EligibilityDecision(False, "evidence coverage is below ranking threshold")
    return EligibilityDecision(True)


def normalize_filter(
    *,
    band: str | None = None,
    dimension: str | None = None,
    language: str | None = None,
    status: str | None = None,
    stale: bool | None = None,
    eligible: bool | None = True,
) -> RankingFilter:
    valid_bands = RANKING_BANDS
    normalized_band = band.strip().lower() if band else None
    if normalized_band and normalized_band not in valid_bands:
        raise ValueError(f"unknown score band: {band}")
    return RankingFilter(
        band=normalized_band,
        dimension=dimension.strip().lower() if dimension else None,
        language=language.strip().lower() if language else None,
        status=status.strip().lower() if status else None,
        stale=stale,
        eligible=eligible,
    )


def matches_filter(
    candidate: RankingCandidate,
    ranking_filter: RankingFilter,
    *,
    now: datetime | None = None,
    policy: RankingPolicy | None = None,
) -> bool:
    if ranking_filter.eligible is not None and candidate.eligible != ranking_filter.eligible:
        return False
    if ranking_filter.band and band_for_score(candidate.overall_score) != ranking_filter.band:
        return False
    if ranking_filter.dimension and candidate.dimensions.get(ranking_filter.dimension) is None:
        return False
    if ranking_filter.language and ranking_filter.language not in {item.lower() for item in candidate.languages}:
        return False
    if ranking_filter.status and candidate.status.lower() != ranking_filter.status:
        return False
    return not (
        ranking_filter.stale is not None
        and is_stale(candidate, now=now, policy=policy) != ranking_filter.stale
    )


def ranking_sort_key(candidate: RankingCandidate) -> tuple[Any, ...]:
    """Score, evidence, freshness, name, ID — all tie-breakers are stable."""
    freshness = _aware(candidate.analyzed_at).timestamp() if candidate.analyzed_at else float("-inf")
    score = (
        candidate.overall_score
        if candidate.overall_score is not None and math.isfinite(candidate.overall_score)
        else float("-inf")
    )
    return (
        -score,
        -candidate.evidence_coverage,
        -freshness,
        candidate.name.casefold(),
        candidate.repository_id,
    )


def rank_candidates(
    candidates: list[RankingCandidate] | tuple[RankingCandidate, ...],
    *,
    ranking_filter: RankingFilter | None = None,
    page: int = 1,
    limit: int = 50,
    now: datetime | None = None,
    policy: RankingPolicy | None = None,
) -> tuple[list[RankingCandidate], int]:
    if page < 1 or limit < 1 or limit > 100:
        raise ValueError("page must be >= 1 and limit must be between 1 and 100")
    ranking_filter = ranking_filter or RankingFilter()
    filtered = [
        candidate
        for candidate in candidates
        if matches_filter(candidate, ranking_filter, now=now, policy=policy)
    ]
    filtered.sort(key=ranking_sort_key)
    start = (page - 1) * limit
    log.debug("ranking_filtered", input_count=len(candidates), output_count=len(filtered), page=page, limit=limit)
    return filtered[start : start + limit], len(filtered)


__all__ = [
    "ALLOWED_RANKING_MODES",
    "DEFAULT_MAX_AGE",
    "DEFAULT_MIN_EVIDENCE_COVERAGE",
    "RANKING_BANDS",
    "RANKING_BAND_THRESHOLDS",
    "EligibilityDecision",
    "RankingCandidate",
    "RankingFilter",
    "RankingPolicy",
    "band_for_score",
    "evaluate_eligibility",
    "grade_for_score",
    "is_stale",
    "matches_filter",
    "normalize_filter",
    "rank_candidates",
    "ranking_sort_key",
]
