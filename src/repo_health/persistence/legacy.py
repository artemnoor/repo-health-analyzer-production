"""Read-only decoder for historical health score records.

This module is intentionally not an analyzer and never calculates a new score.
It only maps fields whose meaning is known into the v1 result contract and
surfaces every unmapped or unavailable part as a limitation.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from typing import Any

from ..contracts.requests import RepositoryRef
from ..contracts.results import (
    AnalysisState,
    AnalysisStatus,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    HealthCategory,
    Limitation,
    RepoHealthResult,
    ScoreBreakdown,
)
from ..scoring.v1 import CATEGORY_KEYS, CATEGORY_ORDER, REPO_HEALTH_SCORE_VERSION

_CATEGORY_IDS = {
    "Documentation": "repo-health.documentation",
    "Activity": "repo-health.activity",
    "Issues": "repo-health.issues",
    "CI/CD": "repo-health.cicd",
    "Security": "repo-health.security",
    "Code Health": "repo-health.code-health",
}
_CATEGORY_ENUMS = {
    "Documentation": HealthCategory.DOCUMENTATION,
    "Activity": HealthCategory.ACTIVITY,
    "Issues": HealthCategory.ISSUES,
    "CI/CD": HealthCategory.CICD,
    "Security": HealthCategory.SECURITY,
    "Code Health": HealthCategory.CODE_HEALTH,
}
_SUPPORTED_LEGACY_SCORE_VERSIONS = frozenset({"repo-health-score-v1", "repo-health-score-v1.0", "v1"})


class LegacyReplayError(ValueError):
    """Historical record is malformed or has no supported score fields."""


def _digest(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized and all(char in "0123456789abcdef" for char in normalized) and 8 <= len(normalized) <= 128:
        return normalized
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _score(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 100.0 else None


def _first_value(payload: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _fraction(value: object, *, default: float = 0.0) -> float:
    """Decode either the historical 0..1 or percentage 0..100 convention."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _coverage(value: object) -> Coverage:
    fraction = _fraction(value, default=1.0)
    if fraction <= 0.0:
        return Coverage(status="unavailable", reason="historical coverage was zero or unavailable")
    covered = round(fraction * 100)
    return Coverage(
        status="complete" if fraction >= 1.0 else "partial",
        covered=covered,
        total=100,
        reason="decoded from historical coverage field",
    )


def _presentation(value: object, *, overall: float | None) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"SCORE", "PROVISIONAL_SCORE", "INSUFFICIENT_DATA"}:
        return normalized
    return "SCORE" if overall is not None else "INSUFFICIENT_DATA"


def _status(value: object, score: float | None) -> CategoryStatus:
    normalized = str(value or "").casefold()
    if normalized in {"unavailable", "skipped", "missing"}:
        return CategoryStatus.SKIPPED
    if normalized in {"error", "failed"}:
        return CategoryStatus.ERROR
    if normalized in {"fail", "critical"}:
        return CategoryStatus.FAIL
    if normalized in {"warn", "warning", "partial"}:
        return CategoryStatus.WARN
    if normalized in {"pass", "measured", "complete", "completed"}:
        return CategoryStatus.PASS
    if score is None:
        return CategoryStatus.INCONCLUSIVE
    return CategoryStatus.PASS if score >= 80 else CategoryStatus.WARN if score >= 50 else CategoryStatus.FAIL


def replay_legacy_score(
    payload: Mapping[str, Any],
    *,
    analysis_id: str,
    repository: RepositoryRef,
) -> RepoHealthResult:
    """Decode a legacy score JSON object without recomputing it."""
    if not isinstance(payload, Mapping):
        raise LegacyReplayError("legacy score must be an object")
    legacy_version = payload.get("score_engine_version")
    if legacy_version is not None and str(legacy_version) not in _SUPPORTED_LEGACY_SCORE_VERSIONS:
        limitation = Limitation(
            code="legacy_unavailable",
            reason=f"Historical score engine version is not supported for replay: {legacy_version}",
            affected_scope="repo-health-score",
        )
        status = AnalysisStatus(analysis_id=analysis_id, state=AnalysisState.PARTIAL, reason=limitation.reason)
        return RepoHealthResult(
            analysis_id=analysis_id,
            repository=repository,
            status=status,
            score_engine_version=REPO_HEALTH_SCORE_VERSION,
            presentation_state="INSUFFICIENT_DATA",
            limitations=(limitation,),
            score_status="inconclusive",
            breakdown=ScoreBreakdown(),
        )
    overall = _score(_first_value(payload, "overall", "score_after_cap", "score"))
    before_caps = _score(_first_value(payload, "score_before_cap", "score_before_caps"))
    raw_scores = payload["category_scores"] if "category_scores" in payload else payload.get("dimensions", {})
    raw_statuses = payload.get("category_statuses", {})
    raw_coverage = payload.get("category_coverage", {})
    raw_confidence = payload.get("category_confidence", {})
    raw_statuses = {} if raw_statuses is None else raw_statuses
    raw_coverage = {} if raw_coverage is None else raw_coverage
    raw_confidence = {} if raw_confidence is None else raw_confidence
    if not isinstance(raw_scores, Mapping):
        raise LegacyReplayError("legacy category scores must be an object")
    if (
        not isinstance(raw_statuses, Mapping)
        or not isinstance(raw_coverage, Mapping)
        or not isinstance(raw_confidence, Mapping)
    ):
        raise LegacyReplayError("legacy category status, coverage and confidence fields must be objects")

    categories: dict[str, CategoryResult | None] = {}
    limitations: list[Limitation] = []
    for name in CATEGORY_ORDER:
        score = _score(raw_scores.get(name, raw_scores.get(CATEGORY_KEYS[name])))
        category_status = _status(raw_statuses.get(name), score)
        coverage = _fraction(raw_coverage.get(name), default=1.0)
        confidence = _fraction(raw_confidence.get(name), default=0.0)
        if score is None or category_status in {
            CategoryStatus.SKIPPED,
            CategoryStatus.ERROR,
            CategoryStatus.INCONCLUSIVE,
        }:
            categories[name] = None
            limitations.append(
                Limitation(
                    code="legacy.category_unavailable",
                    reason=f"Historical {name} category has no known v1 numeric result",
                    affected_scope=name,
                )
            )
            continue
        categories[name] = CategoryResult(
            analysis_id=analysis_id,
            analyzer_id=_CATEGORY_IDS[name],
            analyzer_version="legacy-replay-v1",
            category=_CATEGORY_ENUMS[name],
            status=category_status,
            score=score,
            coverage=_coverage(coverage),
            confidence=Confidence(
                value=confidence,
                level="high" if confidence >= 0.9 else "medium" if confidence >= 0.5 else "unknown",
                reason="decoded from historical score",
            ),
        )
        limitations.append(
            Limitation(
                code="legacy.evidence_unavailable",
                reason=f"Historical {name} evidence was not included in the replay payload",
                affected_scope=name,
            )
        )

    numeric_count = sum(item is not None for item in categories.values())
    state = (
        AnalysisState.COMPLETED
        if numeric_count == len(CATEGORY_ORDER) and overall is not None
        else AnalysisState.PARTIAL
    )
    if overall is None:
        limitations.append(
            Limitation(
                code="legacy.score_unavailable",
                reason="Historical record has no known overall score",
                affected_scope="repo-health-score",
            )
        )
    known_keys = {
        "overall",
        "score",
        "score_after_cap",
        "score_before_cap",
        "score_before_caps",
        "category_scores",
        "dimensions",
        "category_statuses",
        "category_coverage",
        "category_confidence",
        "presentation_state",
        "coverage",
        "coverage_k",
        "confidence",
        "evidence_coverage",
        "applied_caps",
        "score_status",
        "score_config_digest",
        "policy_digest",
        "score_engine_version",
    }
    unknown = sorted(str(key) for key in payload if key not in known_keys)
    if unknown:
        limitations.append(
            Limitation(
                code="legacy.unmapped_fields",
                reason="Historical fields were not mapped: " + ", ".join(unknown[:20]),
                affected_scope="legacy-record",
            )
        )
    status = AnalysisStatus(
        analysis_id=analysis_id,
        state=state,
        completed_analyzer_ids=tuple(item.analyzer_id for item in categories.values() if item is not None),
    )
    scores = {name: item.score if item is not None else None for name, item in categories.items()}
    category_statuses = {
        name: item.status.value if item is not None else "skipped" for name, item in categories.items()
    }
    breakdown = ScoreBreakdown(
        category_scores=scores,
        category_statuses=category_statuses,
        category_coverage={
            name: (item.coverage.covered / item.coverage.total if item and item.coverage.total else 0.0)
            for name, item in categories.items()
        },
        category_confidence={name: (item.confidence.value if item else 0.0) for name, item in categories.items()},
        contributions=(),
    )
    score_status = str(payload.get("score_status") or ("warn" if state is AnalysisState.PARTIAL else "pass"))
    if score_status not in {"pass", "warn", "fail", "inconclusive"}:
        score_status = "inconclusive"
    return RepoHealthResult(
        analysis_id=analysis_id,
        repository=repository,
        status=status,
        overall_score=overall,
        score_before_caps=before_caps,
        score_engine_version=REPO_HEALTH_SCORE_VERSION,
        policy_digest=_digest(payload.get("policy_digest")),
        score_config_digest=_digest(payload.get("score_config_digest")),
        presentation_state=_presentation(payload.get("presentation_state"), overall=overall),
        coverage=_fraction(payload.get("coverage_k", payload.get("coverage", 0.0))),
        confidence=_fraction(payload.get("confidence", 0.0)),
        evidence_coverage=_fraction(payload.get("evidence_coverage", 0.0)),
        coverage_k=_fraction(payload.get("coverage_k", payload.get("coverage", 0.0))),
        applied_caps=tuple(payload.get("applied_caps") or ()),
        limitations=tuple(limitations),
        score_status=score_status,  # type: ignore[arg-type]
        breakdown=breakdown,
        documentation=categories["Documentation"],
        activity=categories["Activity"],
        issues=categories["Issues"],
        cicd=categories["CI/CD"],
        security=categories["Security"],
        code_health=categories["Code Health"],
    )


__all__ = ["LegacyReplayError", "replay_legacy_score"]
