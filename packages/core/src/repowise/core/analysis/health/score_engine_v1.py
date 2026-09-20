"""Versioned six-category Repo Health Score engine.

This module is deliberately independent from the legacy dimension composer.
It consumes analyzer contracts, never raw source payloads, and exposes both
the machine-readable v1 breakdown and compatibility fields used by the
existing persistence projection.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .integrations.contracts import AnalyzerResult, AnalyzerStatus, Limitation

REPO_HEALTH_SCORE_VERSION = "repo-health-score-v1"

CATEGORY_ORDER: tuple[str, ...] = (
    "Documentation",
    "Activity",
    "Issues",
    "CI/CD",
    "Security",
    "Code Health",
)

CATEGORY_KEYS: dict[str, str] = {
    "Documentation": "documentation",
    "Activity": "activity",
    "Issues": "issues",
    "CI/CD": "cicd",
    "Security": "security",
    "Code Health": "code_health",
}

DEFAULT_REPO_HEALTH_WEIGHTS: dict[str, float] = {
    "Documentation": 0.15,
    "Activity": 0.15,
    "Issues": 0.15,
    "CI/CD": 0.15,
    "Security": 0.20,
    "Code Health": 0.20,
}

MISSING_STATUS_VALUES = frozenset(
    {
        "UNAVAILABLE",
        "ERROR",
        "NOT_APPLICABLE",
        "NO_ACTIVITY",
        "CI_NOT_CONFIGURED",
        "NO_RUNS",
        "INSUFFICIENT_HISTORY",
    }
)


class RepoHealthScoreV1(BaseModel):
    """Deterministic v1 score plus explainability and migration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = REPO_HEALTH_SCORE_VERSION
    overall: float | None = Field(default=None, ge=0.0, le=100.0)
    score_before_cap: float | None = Field(default=None, ge=0.0, le=100.0)
    score_after_cap: float | None = Field(default=None, ge=0.0, le=100.0)
    presentation_state: str
    coverage: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    coverage_k: float = Field(ge=0.0, le=1.0)
    configured_weight: float = Field(ge=0.0)
    available_weight: float = Field(ge=0.0)
    numeric_category_count: int = Field(ge=0)
    dimensions: dict[str, float | None]
    category_scores: dict[str, float | None]
    category_statuses: dict[str, str]
    category_coverage: dict[str, float]
    category_confidence: dict[str, float]
    category_quality: dict[str, float]
    contributions: tuple[dict[str, Any], ...] = ()
    breakdown: tuple[dict[str, Any], ...] = ()
    excluded_categories: tuple[str, ...] = ()
    applied_caps: tuple[dict[str, Any], ...] = ()
    limitations: tuple[Limitation, ...] = ()
    status: AnalyzerStatus = AnalyzerStatus.INCONCLUSIVE
    score_config_digest: str

    @property
    def score(self) -> float | None:
        return self.overall


def _bounded(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number)) if math.isfinite(number) else default


def _score(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 100.0 else None


def _nested_mappings(diagnostics: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    pending: list[Mapping[str, Any]] = [diagnostics]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        rows.append(current)
        pending.extend(value for value in current.values() if isinstance(value, Mapping))
    return tuple(rows)


def _diagnostic_number(result: AnalyzerResult, names: tuple[str, ...]) -> float | None:
    for row in _nested_mappings(result.diagnostics):
        for name in names:
            if name in row and row[name] is not None:
                try:
                    value = float(row[name])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    return value
    return None


def _category_status(result: AnalyzerResult) -> str:
    explicit = result.diagnostics.get("category_status") or result.diagnostics.get("status")
    known = MISSING_STATUS_VALUES | {"MEASURED", "PARTIAL", "NO_ISSUES"}
    if isinstance(explicit, str) and explicit.upper() in known:
        return explicit.upper()
    for row in _nested_mappings(result.diagnostics):
        for key in ("security_status", "issues_status", "cicd_status", "pydriller_status", "code_health_status"):
            value = row.get(key)
            if isinstance(value, str) and value.upper() in known:
                return value.upper()
    if result.status is AnalyzerStatus.SKIPPED:
        return "UNAVAILABLE"
    if result.status is AnalyzerStatus.ERROR:
        return "ERROR"
    if result.status is AnalyzerStatus.INCONCLUSIVE and result.score is None:
        return "INSUFFICIENT_DATA"
    if result.score is None and result.status is AnalyzerStatus.WARN:
        return "PARTIAL"
    return "MEASURED"


def _category_for(result: AnalyzerResult) -> str | None:
    analyzer_id = result.analyzer_id.casefold()
    dimension = (result.score_dimension or "").casefold()
    if analyzer_id == "vale.documentation" or "vale" in analyzer_id or dimension in {"docs", "documentation"}:
        return "Documentation"
    if analyzer_id == "chaoss.activity" or "pydriller" in analyzer_id or dimension in {"history", "activity"}:
        return "Activity"
    if analyzer_id in {"chaoss.issues_prs", "issues.sourcecraft"} or "issues" in analyzer_id or dimension == "issues":
        return "Issues"
    if analyzer_id == "cicd.sourcecraft" or "cicd" in analyzer_id or dimension in {"delivery", "ci", "cicd"}:
        return "CI/CD"
    if analyzer_id == "sourcecraft.appsec" or "appsec" in analyzer_id or dimension == "security":
        return "Security"
    if analyzer_id == "repowise.health" or "code_health" in analyzer_id or dimension in {"code", "maintainability", "code_quality"}:
        return "Code Health"
    return None


def _select_category_results(results: Iterable[AnalyzerResult]) -> tuple[dict[str, AnalyzerResult], tuple[str, ...]]:
    selected: dict[str, AnalyzerResult] = {}
    excluded: list[str] = []
    priority = {
        "vale.documentation": 0,
        "chaoss.activity": 0,
        "chaoss.issues_prs": 0,
        "cicd.sourcecraft": 0,
        "sourcecraft.appsec": 0,
        "repowise.health": 0,
    }
    for result in results:
        category = _category_for(result)
        if category is None:
            continue
        current = selected.get(category)
        if current is None:
            selected[category] = result
            continue
        current_rank = (priority.get(current.analyzer_id, 1), -(current.score if current.score is not None else -1.0), current.analyzer_id)
        candidate_rank = (priority.get(result.analyzer_id, 1), -(result.score if result.score is not None else -1.0), result.analyzer_id)
        if candidate_rank < current_rank:
            excluded.append(current.analyzer_id)
            selected[category] = result
        else:
            excluded.append(result.analyzer_id)
    return selected, tuple(sorted(excluded))


def _coverage_confidence(result: AnalyzerResult) -> tuple[float, float]:
    coverage = _diagnostic_number(result, ("coverage", "facts_coverage", "pydriller_coverage", "score_coverage"))
    confidence = _diagnostic_number(result, ("confidence", "facts_confidence", "pydriller_confidence"))
    if coverage is None:
        coverage = result.available_weight / result.total_weight if result.total_weight > 0 else (1.0 if result.score is not None else 0.0)
    if confidence is None:
        refs = [ref.confidence for ref in result.evidence if ref.confidence is not None]
        confidence = sum(refs) / len(refs) if refs else (1.0 if result.score is not None else 0.0)
    return _bounded(coverage), _bounded(confidence)


def _security_cap(result: AnalyzerResult | None) -> tuple[float | None, str | None]:
    if result is None:
        return None, None
    active = int(_diagnostic_number(result, ("active_findings", "active_finding_count")) or 0)
    critical = int(_diagnostic_number(result, ("critical_findings",)) or 0)
    high = int(_diagnostic_number(result, ("high_findings",)) or 0)
    secrets = int(_diagnostic_number(result, ("confirmed_secret_count", "secret_findings")) or 0)
    if secrets > 0:
        return 40.0, "confirmed_secret"
    if critical > 0:
        return 40.0, "confirmed_critical"
    if high > 0:
        return 60.0, "confirmed_high"
    if active > 0:
        for finding in result.findings:
            if finding.severity == "critical":
                return 40.0, "confirmed_critical"
            if finding.severity == "high":
                return 60.0, "confirmed_high"
    return None, None


def _config_digest(weights: Mapping[str, float], minimum_score_categories: int, minimum_provisional_categories: int, score_k: float, provisional_k: float) -> str:
    payload = {
        "version": REPO_HEALTH_SCORE_VERSION,
        "weights": dict(weights),
        "minimum_score_categories": minimum_score_categories,
        "minimum_provisional_categories": minimum_provisional_categories,
        "score_k": score_k,
        "provisional_k": provisional_k,
        "security_caps": {"confirmed_high": 60.0, "confirmed_critical": 40.0, "confirmed_secret": 40.0},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def compose_repo_health_score_v1(
    results: Iterable[AnalyzerResult],
    *,
    weights: Mapping[str, float] | None = None,
    minimum_score_categories: int = 5,
    minimum_provisional_categories: int = 4,
    score_k: float = 0.75,
    provisional_k: float = 0.50,
) -> RepoHealthScoreV1:
    """Compose the frozen v1 score deterministically from category results."""
    configured = dict(DEFAULT_REPO_HEALTH_WEIGHTS if weights is None else weights)
    configured = {category: max(0.0, float(configured.get(category, 0.0))) for category in CATEGORY_ORDER}
    total_weight = sum(configured.values())
    if total_weight <= 0:
        raise ValueError("Repo Health v1 requires at least one positive category weight")
    configured = {category: value / total_weight for category, value in configured.items()}
    selected, excluded = _select_category_results(results)
    scores: dict[str, float | None] = {category: None for category in CATEGORY_ORDER}
    statuses: dict[str, str] = {category: "UNAVAILABLE" for category in CATEGORY_ORDER}
    coverages: dict[str, float] = {category: 0.0 for category in CATEGORY_ORDER}
    confidences: dict[str, float] = {category: 0.0 for category in CATEGORY_ORDER}
    qualities: dict[str, float] = {category: 0.0 for category in CATEGORY_ORDER}
    contributions: list[dict[str, Any]] = []
    numeric_categories: list[str] = []
    limitations: list[Limitation] = []

    for category in CATEGORY_ORDER:
        result = selected.get(category)
        if result is None:
            limitations.append(Limitation(reason=f"{category} has no analyzer result", kind="missing_capability", affected_scope=category))
            continue
        status = _category_status(result)
        coverage, confidence = _coverage_confidence(result)
        value = _score(result.score)
        if status in MISSING_STATUS_VALUES or value is None:
            value = None
        scores[category] = value
        statuses[category] = status
        coverages[category] = coverage
        confidences[category] = confidence
        qualities[category] = coverage * confidence if value is not None else 0.0
        if value is not None:
            numeric_categories.append(category)
        else:
            limitations.append(Limitation(reason=f"{category} is not numerically measurable ({status})", kind="missing_capability", affected_scope=category))
        contributions.append({
            "category": category,
            "analyzer_id": result.analyzer_id,
            "score": value,
            "weight": configured[category],
            "coverage": coverage,
            "confidence": confidence,
            "quality": qualities[category],
            "weighted_points": configured[category] * value if value is not None else None,
            "excluded_from_denominator": value is None,
            "status": status,
        })

    available_weight = sum(configured[category] for category in numeric_categories)
    raw = (
        sum(configured[category] * (scores[category] or 0.0) for category in numeric_categories) / available_weight
        if available_weight > 0
        else None
    )
    k = sum(configured[category] * qualities[category] for category in CATEGORY_ORDER)
    evidence_coverage = sum(configured[category] * coverages[category] for category in CATEGORY_ORDER)
    confidence = sum(configured[category] * confidences[category] for category in CATEGORY_ORDER)
    numeric_count = len(numeric_categories)
    if numeric_count >= minimum_score_categories and k >= score_k:
        state = "SCORE"
    elif numeric_count >= minimum_provisional_categories and k >= provisional_k:
        state = "PROVISIONAL_SCORE"
    else:
        state = "INSUFFICIENT_DATA"

    caps: list[dict[str, Any]] = []
    cap, reason = _security_cap(selected.get("Security"))
    after_cap = raw
    if after_cap is not None and cap is not None and after_cap > cap:
        after_cap = cap
        caps.append({"category": "Security", "cap": cap, "reason": reason})
    if state == "INSUFFICIENT_DATA":
        after_cap = None
        limitations.append(Limitation(reason="Minimum category count or weighted coverage K was not met", kind="insufficient_denominator", affected_scope="repo-health-score"))
    final_status = AnalyzerStatus.INCONCLUSIVE
    if state != "INSUFFICIENT_DATA":
        if any(row.get("reason") in {"confirmed_critical", "confirmed_secret"} for row in caps):
            final_status = AnalyzerStatus.FAIL
        elif state == "PROVISIONAL_SCORE" or caps or len(numeric_categories) < len(CATEGORY_ORDER):
            final_status = AnalyzerStatus.WARN
        else:
            final_status = AnalyzerStatus.PASS

    digest = _config_digest(configured, minimum_score_categories, minimum_provisional_categories, score_k, provisional_k)
    return RepoHealthScoreV1(
        overall=after_cap,
        score_before_cap=raw,
        score_after_cap=after_cap,
        presentation_state=state,
        coverage=k,
        confidence=_bounded(confidence),
        evidence_coverage=_bounded(evidence_coverage),
        coverage_k=_bounded(k),
        configured_weight=1.0,
        available_weight=available_weight,
        numeric_category_count=numeric_count,
        dimensions={CATEGORY_KEYS[category]: scores[category] for category in CATEGORY_ORDER},
        category_scores={category: scores[category] for category in CATEGORY_ORDER},
        category_statuses=statuses,
        category_coverage=coverages,
        category_confidence=confidences,
        category_quality=qualities,
        contributions=tuple(contributions),
        breakdown=tuple(contributions),
        excluded_categories=excluded,
        applied_caps=tuple(caps),
        limitations=tuple(limitations),
        status=final_status,
        score_config_digest=digest,
    )


def compare_score_engines(results: Iterable[AnalyzerResult], *, repository_id: str | None = None) -> dict[str, Any]:
    """Return a migration comparison without changing the legacy engine."""
    from .composite import compose_health_score

    materialized = tuple(results)
    legacy = compose_health_score(materialized, repository_id=repository_id)
    current = compose_repo_health_score_v1(materialized)
    return {
        "legacy": legacy.model_dump(mode="json"),
        "repo_health_v1": current.model_dump(mode="json"),
        "delta": (current.overall - legacy.overall) if current.overall is not None and legacy.overall is not None else None,
    }


def compose_default_repo_health_score(
    results: Iterable[AnalyzerResult],
    config: Mapping[str, Any] | None = None,
    *,
    repository_id: str | None = None,
) -> Any:
    """Use v1 for the six-category pipeline and legacy composition otherwise.

    The fallback is intentionally narrow: it keeps older callers and custom
    analyzer registries operational during migration, while any recognized
    Repo Health category result selects the new production policy.
    """
    materialized = tuple(results)
    recognized_categories = {_category_for(result) for result in materialized} - {None}
    recognized = len(recognized_categories) >= 2
    config_is_v1 = isinstance(config, Mapping) and (
        any(str(key) in CATEGORY_ORDER for key in (config.get("weights") or {}))
        or str(config.get("version", "")).startswith(REPO_HEALTH_SCORE_VERSION)
    )
    if recognized and (config is None or config_is_v1):
        raw = config.get("weights") if isinstance(config, Mapping) else None
        return compose_repo_health_score_v1(materialized, weights=raw if isinstance(raw, Mapping) else None)
    if recognized and config is None:
        return compose_repo_health_score_v1(materialized)
    from .composite import compose_health_score

    return compose_health_score(materialized, config, repository_id=repository_id)


__all__ = [
    "CATEGORY_ORDER",
    "DEFAULT_REPO_HEALTH_WEIGHTS",
    "REPO_HEALTH_SCORE_VERSION",
    "RepoHealthScoreV1",
    "compare_score_engines",
    "compose_default_repo_health_score",
    "compose_repo_health_score_v1",
]
