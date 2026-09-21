"""Pure six-category Repo Health Score v1 implementation.

The arithmetic intentionally follows the proven ``score_engine_v1`` order:
normalize weights, exclude non-numeric categories from the denominator,
calculate weighted coverage K, apply presentation thresholds, then apply the
security cap.  This module has no provider, API or persistence dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog

from ..contracts.results import (
    AnalysisState,
    AnalysisStatus,
    CategoryResult,
    CategoryStatus,
    Limitation,
    RepoHealthResult,
    ScoreBreakdown,
    ScoreInput,
)

log = structlog.get_logger("repo_health.scoring.v1")

REPO_HEALTH_SCORE_VERSION = "repo-health-score-v1"
CATEGORY_ORDER = ("Documentation", "Activity", "Issues", "CI/CD", "Security", "Code Health")
CATEGORY_KEYS = {
    "Documentation": "documentation",
    "Activity": "activity",
    "Issues": "issues",
    "CI/CD": "cicd",
    "Security": "security",
    "Code Health": "code_health",
}
DEFAULT_REPO_HEALTH_WEIGHTS = {
    "Documentation": 0.15,
    "Activity": 0.15,
    "Issues": 0.15,
    "CI/CD": 0.15,
    "Security": 0.20,
    "Code Health": 0.20,
}
MISSING_STATUS_VALUES = frozenset({"skipped", "error", "inconclusive"})


@dataclass(frozen=True, slots=True)
class ScorePolicyV1:
    version: str = REPO_HEALTH_SCORE_VERSION
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_REPO_HEALTH_WEIGHTS))
    minimum_score_categories: int = 5
    minimum_provisional_categories: int = 4
    score_k: float = 0.75
    provisional_k: float = 0.50

    def __post_init__(self) -> None:
        if self.minimum_score_categories < 1 or self.minimum_score_categories > len(CATEGORY_ORDER):
            raise ValueError("minimum_score_categories must fit the six canonical categories")
        if (
            self.minimum_provisional_categories < 1
            or self.minimum_provisional_categories > self.minimum_score_categories
        ):
            raise ValueError("minimum_provisional_categories must not exceed minimum_score_categories")
        if not 0.0 < self.provisional_k <= self.score_k <= 1.0:
            raise ValueError("score coverage thresholds must satisfy 0 < provisional_k <= score_k <= 1")

    def normalized_weights(self) -> dict[str, float]:
        raw = dict(self.weights)
        if set(raw) - set(CATEGORY_ORDER):
            raise ValueError("Score v1 weights contain unknown categories")
        values = {category: max(0.0, float(raw.get(category, 0.0))) for category in CATEGORY_ORDER}
        total = sum(values.values())
        if total <= 0:
            raise ValueError("Repo Health v1 requires at least one positive category weight")
        return {category: values[category] / total for category in CATEGORY_ORDER}

    def digest(self) -> str:
        payload = {
            "version": self.version,
            "weights": self.normalized_weights(),
            "minimum_score_categories": self.minimum_score_categories,
            "minimum_provisional_categories": self.minimum_provisional_categories,
            "score_k": self.score_k,
            "provisional_k": self.provisional_k,
            "security_caps": {"confirmed_high": 60.0, "confirmed_critical": 40.0, "confirmed_secret": 40.0},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ScoreEngineV1:
    """The only active production score formula."""

    def __init__(self, policy: ScorePolicyV1 | None = None) -> None:
        self.policy = policy or ScorePolicyV1()
        if self.policy.version != REPO_HEALTH_SCORE_VERSION:
            raise ValueError(f"unsupported score policy: {self.policy.version}")

    def score(self, score_input: ScoreInput) -> RepoHealthResult:
        weights = self.policy.normalized_weights()
        selected = {
            "Documentation": score_input.documentation,
            "Activity": score_input.activity,
            "Issues": score_input.issues,
            "CI/CD": score_input.cicd,
            "Security": score_input.security,
            "Code Health": score_input.code_health,
        }
        scores: dict[str, float | None] = {category: None for category in CATEGORY_ORDER}
        statuses: dict[str, str] = {category: "skipped" for category in CATEGORY_ORDER}
        coverages: dict[str, float] = {category: 0.0 for category in CATEGORY_ORDER}
        confidences: dict[str, float] = {category: 0.0 for category in CATEGORY_ORDER}
        qualities: dict[str, float] = {category: 0.0 for category in CATEGORY_ORDER}
        contributions: list[dict[str, Any]] = []
        numeric: list[str] = []
        limitations: list[Limitation] = []
        failed: list[str] = []

        for category in CATEGORY_ORDER:
            result = selected[category]
            if result is None:
                limitations.append(
                    Limitation(
                        code="missing_capability", reason=f"{category} has no analyzer result", affected_scope=category
                    )
                )
                continue
            statuses[category] = result.status.value
            if result.status in {CategoryStatus.ERROR, CategoryStatus.SKIPPED}:
                failed.append(result.analyzer_id)
            coverage = _bounded(_coverage(result))
            confidence = _bounded(result.confidence.value)
            value = _score(result.score)
            if result.status.value in MISSING_STATUS_VALUES or value is None:
                value = None
            scores[category] = value
            coverages[category] = coverage
            confidences[category] = confidence
            qualities[category] = coverage * confidence if value is not None else 0.0
            if value is not None:
                numeric.append(category)
            else:
                limitations.append(
                    Limitation(
                        code="missing_capability",
                        reason=f"{category} is not numerically measurable ({result.status.value})",
                        affected_scope=category,
                    )
                )
            contributions.append(
                {
                    "category": category,
                    "analyzer_id": result.analyzer_id,
                    "score": value,
                    "weight": weights[category],
                    "coverage": coverage,
                    "confidence": confidence,
                    "quality": qualities[category],
                    "weighted_points": weights[category] * value if value is not None else None,
                    "excluded_from_denominator": value is None,
                    "status": statuses[category],
                }
            )

        available_weight = sum(weights[category] for category in numeric)
        raw = (
            sum(weights[category] * (scores[category] or 0.0) for category in numeric) / available_weight
            if available_weight
            else None
        )
        coverage_k = sum(weights[category] * qualities[category] for category in CATEGORY_ORDER)
        evidence_coverage = sum(weights[category] * coverages[category] for category in CATEGORY_ORDER)
        confidence = _bounded(sum(weights[category] * confidences[category] for category in CATEGORY_ORDER))
        if len(numeric) >= self.policy.minimum_score_categories and coverage_k >= self.policy.score_k:
            presentation = "SCORE"
        elif len(numeric) >= self.policy.minimum_provisional_categories and coverage_k >= self.policy.provisional_k:
            presentation = "PROVISIONAL_SCORE"
        else:
            presentation = "INSUFFICIENT_DATA"

        caps: list[dict[str, Any]] = []
        cap, cap_reason = _security_cap(score_input.security)
        after_cap = raw
        if after_cap is not None and cap is not None and after_cap > cap:
            after_cap = cap
            caps.append({"category": "Security", "cap": cap, "reason": cap_reason})
        if presentation == "INSUFFICIENT_DATA":
            after_cap = None
            limitations.append(
                Limitation(
                    code="insufficient_denominator",
                    reason="Minimum category count or weighted coverage K was not met",
                    affected_scope="repo-health-score",
                )
            )
        if presentation == "INSUFFICIENT_DATA":
            score_status = "inconclusive"
        elif cap_reason in {"confirmed_critical", "confirmed_secret"}:
            score_status = "fail"
        elif presentation == "PROVISIONAL_SCORE" or caps or len(numeric) < len(CATEGORY_ORDER):
            score_status = "warn"
        else:
            score_status = "pass"
        state = AnalysisState.COMPLETED if len(numeric) == len(CATEGORY_ORDER) else AnalysisState.PARTIAL
        status = AnalysisStatus(
            analysis_id=score_input.analysis_id,
            state=state,
            completed_analyzer_ids=tuple(
                result.analyzer_id
                for result in selected.values()
                if result is not None and result.status not in {CategoryStatus.ERROR, CategoryStatus.SKIPPED}
            ),
            failed_analyzer_ids=tuple(failed),
        )
        breakdown = ScoreBreakdown(
            category_scores=scores,
            category_statuses=statuses,
            category_coverage=coverages,
            category_confidence=confidences,
            category_quality=qualities,
            contributions=tuple(contributions),
            applied_caps=tuple(caps),
        )
        result = RepoHealthResult(
            analysis_id=score_input.analysis_id,
            repository=score_input.repository,
            status=status,
            overall_score=after_cap,
            score_before_caps=raw,
            score_engine_version=REPO_HEALTH_SCORE_VERSION,
            policy_digest=score_input.policy_digest,
            score_config_digest=self.policy.digest(),
            presentation_state=presentation,
            coverage=coverage_k,
            confidence=confidence,
            evidence_coverage=_bounded(evidence_coverage),
            coverage_k=_bounded(coverage_k),
            applied_caps=tuple(caps),
            limitations=tuple(limitations),
            score_status=score_status,
            documentation=score_input.documentation,
            activity=score_input.activity,
            issues=score_input.issues,
            cicd=score_input.cicd,
            security=score_input.security,
            code_health=score_input.code_health,
            breakdown=breakdown,
        )
        log.info(
            "score_v1_completed",
            analysis_id=result.analysis_id,
            policy_digest=result.score_config_digest,
            presentation_state=presentation,
            score_status=score_status,
            numeric_category_count=len(numeric),
            score=result.overall_score,
        )
        return result


def _bounded(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number)) if math.isfinite(number) else 0.0


def _score(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 100.0 else None


def _coverage(result: CategoryResult) -> float:
    if result.coverage.total_weight and result.coverage.covered_weight is not None:
        return result.coverage.covered_weight / result.coverage.total_weight
    if result.coverage.total:
        return result.coverage.covered / result.coverage.total
    return 1.0 if result.score is not None else 0.0


def _security_cap(result: CategoryResult | None) -> tuple[float | None, str | None]:
    if result is None:
        return None, None
    signals = result.score_signals
    if signals.get("confirmed_secret_count", 0) or signals.get("secret_findings", 0):
        return 40.0, "confirmed_secret"
    if signals.get("critical_findings", 0):
        return 40.0, "confirmed_critical"
    if signals.get("high_findings", 0):
        return 60.0, "confirmed_high"
    return None, None


__all__ = [
    "CATEGORY_ORDER",
    "DEFAULT_REPO_HEALTH_WEIGHTS",
    "REPO_HEALTH_SCORE_VERSION",
    "ScoreEngineV1",
    "ScorePolicyV1",
]
