"""Canonical repository-health score composition.

The upstream analyzers remain the owners of their measurements.  This module
is the deliberately small composition boundary: it turns source-level scores
and evidence-backed ``MetricValue`` rows into one explainable, versioned
0--100 score.  The arithmetic follows the weighted arithmetic mean used by
the copied Criticality implementation, while Criticality itself is never an
input to health.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .integrations.contracts import (
    AnalyzerResult,
    AnalyzerStatus,
    Limitation,
    MetricValue,
)

log = structlog.get_logger("health.composite")

CANONICAL_DIMENSIONS: tuple[str, ...] = (
    "code",
    "history",
    "tests",
    "dependencies",
    "security",
    "delivery",
    "community",
    "docs",
)

DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    "code": 0.25,
    "history": 0.15,
    "tests": 0.15,
    "dependencies": 0.10,
    "security": 0.15,
    "delivery": 0.10,
    "community": 0.05,
    "docs": 0.05,
}

# Names already emitted by the existing adapters and by the copied sources.
# This is a compatibility map, not a second scoring system.
_DIMENSION_ALIASES: dict[str, str] = {
    "code_quality": "code",
    "quality": "code",
    "maintainability": "code",
    "defect": "code",
    "performance": "code",
    "structural": "code",
    "duplication": "code",
    "churn": "history",
    "activity": "history",
    "temporal": "history",
    "contributors": "community",
    "governance": "community",
    "priority": "community",
    "documentation": "docs",
    "repository_hygiene": "docs",
    "repository-hygiene": "docs",
    "ci": "delivery",
    "cicd": "delivery",
    "build": "delivery",
    "testing": "tests",
    "coverage": "tests",
    "deps": "dependencies",
    "dependency": "dependencies",
    "security_ci": "security",
}

_ANALYZER_SCORE_DIMENSIONS: dict[str, str] = {
    "repowise.health": "code",
    "repohealth.baseline": "docs",
    "scorecard.local": "security",
    "qlty.check": "code",
    "sokrates.analysis": "code",
    "forge.community": "community",
    "forge.metadata": "docs",
    "chaoss.metrics": "history",
    "temporal.events": "history",
    "identity.resolution": "community",
    "dependency.graph": "dependencies",
}


class CompositeScoreConfig(BaseModel):
    """Validated, serializable score policy used for scoring and replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(default="health-score-v1", min_length=1)
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_DIMENSION_WEIGHTS))
    min_evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("weights", mode="before")
    @classmethod
    def _normalize_weights(cls, value: object) -> dict[str, float]:
        if value is None:
            return dict(DEFAULT_DIMENSION_WEIGHTS)
        if not isinstance(value, Mapping):
            raise ValueError("weights must be a mapping")
        normalized: dict[str, float] = {}
        for key, raw in value.items():
            name = _canonical_dimension(str(key))
            try:
                weight = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid weight for {key!r}") from exc
            if weight < 0:
                raise ValueError(f"weight for {key!r} cannot be negative")
            if name in CANONICAL_DIMENSIONS:
                normalized[name] = weight
        return {dimension: normalized.get(dimension, 0.0) for dimension in CANONICAL_DIMENSIONS}

    @model_validator(mode="after")
    def _has_weight(self) -> CompositeScoreConfig:
        if sum(self.weights.values()) <= 0:
            raise ValueError("at least one dimension weight must be positive")
        return self

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> CompositeScoreConfig:
        if value is None:
            return cls()
        raw = dict(value)
        if isinstance(raw.get("health_score"), Mapping):
            raw = dict(raw["health_score"])
        quality = raw.pop("quality", None)
        if isinstance(quality, Mapping) and "min_evidence_coverage" not in raw:
            raw["min_evidence_coverage"] = quality.get("min_evidence_coverage", 0.0)
        return cls.model_validate(raw)

    @property
    def digest(self) -> str:
        canonical = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ScoreContribution:
    """One source's non-double-counted contribution to a dimension."""

    analyzer_id: str
    source: str
    dimension: str
    score: float
    weight: float
    confidence: float
    evidence_coverage: float
    metric_name: str | None = None
    denominator: int | None = None
    status: str = "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "analyzer_id": self.analyzer_id,
            "source": self.source,
            "dimension": self.dimension,
            "score": self.score,
            "weight": self.weight,
            "confidence": self.confidence,
            "evidence_coverage": self.evidence_coverage,
            "metric_name": self.metric_name,
            "denominator": self.denominator,
            "status": self.status,
        }


class CompositeHealthScore(BaseModel):
    """Explainable result consumed by persistence, API and ranking layers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    overall: float | None = Field(default=None, ge=0.0, le=100.0)
    dimensions: dict[str, float | None]
    breakdown: tuple[dict[str, Any], ...] = ()
    configured_weight: float = Field(ge=0.0)
    available_weight: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    status: AnalyzerStatus
    limitations: tuple[Limitation, ...] = ()
    score_config_digest: str = Field(min_length=1)


def _canonical_dimension(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if normalized in CANONICAL_DIMENSIONS:
        return normalized
    if normalized in _DIMENSION_ALIASES:
        return _DIMENSION_ALIASES[normalized]
    # Adapter metric names commonly use ``dimension:metric``.
    prefix = normalized.split(":", 1)[0]
    if prefix in CANONICAL_DIMENSIONS:
        return prefix
    return _DIMENSION_ALIASES.get(prefix, "")


def _metric_dimension(result: AnalyzerResult, metric: MetricValue) -> str:
    explicit = _canonical_dimension(metric.dimension)
    if explicit:
        return explicit
    diagnostic = result.diagnostics.get("dimension")
    explicit = _canonical_dimension(str(diagnostic)) if diagnostic else ""
    if explicit:
        return explicit
    return _canonical_dimension(metric.name)


def _score_dimension(result: AnalyzerResult) -> str:
    explicit = _canonical_dimension(result.score_dimension)
    if explicit:
        return explicit
    return _ANALYZER_SCORE_DIMENSIONS.get(result.analyzer_id, "")


def _metric_coverage(metric: MetricValue) -> float | None:
    if metric.denominator is None or metric.denominator <= 0:
        return None
    if not metric.evidence_refs:
        return 0.0
    return sum(max(0.0, min(1.0, ref.confidence)) for ref in metric.evidence_refs) / len(metric.evidence_refs)


def _result_coverage(result: AnalyzerResult) -> float | None:
    if result.total_weight <= 0 or result.available_weight <= 0:
        return None
    evidence = list(result.evidence)
    evidence_confidence = (
        sum(max(0.0, min(1.0, ref.confidence)) for ref in evidence) / len(evidence)
        if evidence
        else 0.0
    )
    return max(0.0, min(1.0, result.available_weight / result.total_weight)) * evidence_confidence


def _status(results: Iterable[AnalyzerResult], has_score: bool) -> AnalyzerStatus:
    statuses = {result.status for result in results}
    if not has_score:
        return AnalyzerStatus.ERROR if AnalyzerStatus.ERROR in statuses else AnalyzerStatus.INCONCLUSIVE
    if AnalyzerStatus.ERROR in statuses:
        return AnalyzerStatus.WARN
    if AnalyzerStatus.FAIL in statuses:
        return AnalyzerStatus.FAIL
    if AnalyzerStatus.WARN in statuses or AnalyzerStatus.INCONCLUSIVE in statuses or AnalyzerStatus.SKIPPED in statuses:
        return AnalyzerStatus.WARN
    return AnalyzerStatus.PASS


def compose_health_score(
    results: Iterable[AnalyzerResult],
    config: CompositeScoreConfig | Mapping[str, Any] | None = None,
    *,
    repository_id: str | None = None,
) -> CompositeHealthScore:
    """Compose a deterministic health score from available source evidence.

    A source contributes at most once per canonical dimension.  If it emits
    scored metrics, those metrics are aggregated first; its aggregate
    ``AnalyzerResult.score`` is only used as a fallback.  Metrics without a
    positive denominator are reported as unavailable rather than treated as 0.
    """

    try:
        policy = config if isinstance(config, CompositeScoreConfig) else CompositeScoreConfig.from_mapping(config)
    except (TypeError, ValueError) as exc:
        log.error("invalid_score_configuration", error_type=type(exc).__name__)
        raise

    materialized = tuple(results)
    configured_weight = sum(policy.weights.values())
    source_dimensions: dict[tuple[str, str], list[ScoreContribution]] = defaultdict(list)
    limitations: list[Limitation] = []

    for result in materialized:
        if result.analyzer_id == "criticality.importance":
            log.debug("excluded_criticality", analyzer_id=result.analyzer_id)
            continue

        # Legacy adapters persisted metric names before ``MetricValue.dimension``
        # existed. When an aggregate source score is present, keep that
        # source-owned score authoritative until the adapter emits explicit
        # canonical dimensions; this preserves replay compatibility without
        # allowing a source score and its component rows to double count.
        has_explicit_metric_dimension = any(bool(metric.dimension) for metric in result.metrics)
        metric_rows: list[tuple[MetricValue, str, float]] = []
        for metric in result.metrics:
            if result.score is not None and not has_explicit_metric_dimension:
                log.debug("excluded_legacy_metric_in_favor_of_aggregate", analyzer_id=result.analyzer_id, metric=metric.name)
                continue
            if metric.score is None:
                log.debug("excluded_metric_without_score", analyzer_id=result.analyzer_id, metric=metric.name)
                continue
            dimension = _metric_dimension(result, metric)
            coverage = _metric_coverage(metric)
            if not dimension or dimension not in policy.weights:
                log.debug("excluded_metric_without_dimension", analyzer_id=result.analyzer_id, metric=metric.name)
                continue
            if coverage is None:
                limitations.append(
                    Limitation(
                        reason=f"Metric {metric.name} has no positive denominator",
                        kind="insufficient_denominator",
                        affected_scope=dimension,
                    )
                )
                log.debug("excluded_metric_without_denominator", analyzer_id=result.analyzer_id, metric=metric.name)
                continue
            metric_rows.append((metric, dimension, coverage))

        if metric_rows:
            grouped: dict[str, list[tuple[MetricValue, float]]] = defaultdict(list)
            for metric, dimension, coverage in metric_rows:
                grouped[dimension].append((metric, coverage))
            for dimension, rows in sorted(grouped.items()):
                denominator = sum(int(metric.denominator or 0) for metric, _coverage in rows) or None
                weight = sum(float(metric.denominator or 1) for metric, _coverage in rows)
                score = sum(float(metric.score or 0.0) * float(metric.denominator or 1) for metric, _coverage in rows) / weight
                coverage = sum(coverage * float(metric.denominator or 1) for metric, coverage in rows) / weight
                confidence = sum(
                    float(ref.confidence)
                    for metric, _coverage in rows
                    for ref in metric.evidence_refs
                ) / max(1, sum(len(metric.evidence_refs) for metric, _coverage in rows))
                source_dimensions[(result.analyzer_id, dimension)].append(
                    ScoreContribution(
                        analyzer_id=result.analyzer_id,
                        source=next(iter(result.source_versions), result.analyzer_id),
                        dimension=dimension,
                        score=max(0.0, min(100.0, score)),
                        weight=weight,
                        confidence=max(0.0, min(1.0, confidence)),
                        evidence_coverage=max(0.0, min(1.0, coverage)),
                        metric_name=rows[0][0].name if len(rows) == 1 else None,
                        denominator=denominator,
                        status=result.status.value,
                    )
                )
            continue

        dimension = _score_dimension(result)
        coverage = _result_coverage(result)
        if result.score is None or not dimension or coverage is None:
            if result.score is not None and not dimension:
                limitations.append(Limitation(reason=f"No canonical dimension for analyzer {result.analyzer_id}", kind="unsupported"))
            elif result.score is not None:
                limitations.append(Limitation(reason=f"Analyzer {result.analyzer_id} has insufficient evidence", kind="insufficient_denominator"))
            log.debug("excluded_result", analyzer_id=result.analyzer_id, dimension=dimension or None)
            continue
        source_dimensions[(result.analyzer_id, dimension)].append(
            ScoreContribution(
                analyzer_id=result.analyzer_id,
                source=next(iter(result.source_versions), result.analyzer_id),
                dimension=dimension,
                score=max(0.0, min(100.0, float(result.score))),
                weight=max(0.01, float(result.available_weight)),
                confidence=coverage,
                evidence_coverage=coverage,
                status=result.status.value,
            )
        )

    dimension_contributions: dict[str, list[ScoreContribution]] = defaultdict(list)
    for (_analyzer_id, dimension), contributions in sorted(source_dimensions.items()):
        # An analyzer/dimension is a single source contribution. The list is
        # retained for forward compatibility with adapters that emit multiple
        # fragments; aggregation here prevents accidental double counting.
        if len(contributions) == 1:
            dimension_contributions[dimension].append(contributions[0])
        else:
            total = sum(item.weight for item in contributions)
            dimension_contributions[dimension].append(
                ScoreContribution(
                    analyzer_id=contributions[0].analyzer_id,
                    source=contributions[0].source,
                    dimension=dimension,
                    score=sum(item.score * item.weight for item in contributions) / total,
                    weight=total,
                    confidence=sum(item.confidence * item.weight for item in contributions) / total,
                    evidence_coverage=sum(item.evidence_coverage * item.weight for item in contributions) / total,
                    metric_name=None,
                    denominator=sum(item.denominator or 0 for item in contributions) or None,
                    status=contributions[0].status,
                )
            )

    dimensions: dict[str, float | None] = {}
    available_weight = 0.0
    weighted_score = 0.0
    weighted_coverage = 0.0
    weighted_confidence = 0.0
    breakdown: list[dict[str, Any]] = []
    for dimension in CANONICAL_DIMENSIONS:
        rows = dimension_contributions.get(dimension, [])
        dimension_weight = policy.weights.get(dimension, 0.0)
        if not rows or dimension_weight <= 0:
            dimensions[dimension] = None
            limitations.append(Limitation(reason=f"Dimension {dimension} is not measured", kind="missing_capability", affected_scope=dimension))
            log.warning("incomplete_dimension", dimension=dimension, repository_id=repository_id)
            continue
        total = sum(row.weight for row in rows)
        score = sum(row.score * row.weight for row in rows) / total
        confidence = sum(row.confidence * row.weight for row in rows) / total
        evidence = sum(row.evidence_coverage * row.weight for row in rows) / total
        dimensions[dimension] = round(max(0.0, min(100.0, score)), 4)
        available_weight += dimension_weight
        weighted_score += score * dimension_weight
        weighted_coverage += evidence * dimension_weight
        weighted_confidence += confidence * dimension_weight
        for row in rows:
            item = row.as_dict()
            item["configured_dimension_weight"] = dimension_weight
            breakdown.append(item)

    overall = weighted_score / available_weight if available_weight else None
    coverage = weighted_coverage / configured_weight if configured_weight else 0.0
    confidence = weighted_confidence / configured_weight if configured_weight else 0.0
    evidence_coverage = coverage
    if overall is None:
        limitations.append(Limitation(reason="No health dimension has usable evidence", kind="insufficient_denominator"))
    elif coverage < policy.min_evidence_coverage:
        limitations.append(Limitation(reason="Health score evidence coverage is below policy threshold", kind="insufficient_denominator"))

    result = CompositeHealthScore(
        overall=round(max(0.0, min(100.0, overall)), 4) if overall is not None else None,
        dimensions=dimensions,
        breakdown=tuple(sorted(breakdown, key=lambda item: (item["dimension"], item["analyzer_id"], item.get("metric_name") or ""))),
        configured_weight=configured_weight,
        available_weight=available_weight,
        confidence=max(0.0, min(1.0, confidence)),
        coverage=max(0.0, min(1.0, coverage)),
        evidence_coverage=max(0.0, min(1.0, evidence_coverage)),
        status=_status(materialized, overall is not None),
        limitations=tuple(limitation for index, limitation in enumerate(limitations) if limitation not in limitations[:index]),
        score_config_digest=policy.digest,
    )
    if result.overall is not None:
        log.info(
            "score_completed",
            repository_id=repository_id,
            score_config_digest=result.score_config_digest,
            overall=result.overall,
            available_weight=result.available_weight,
            coverage=result.coverage,
        )
    else:
        log.warning("score_unavailable", repository_id=repository_id, limitations=len(result.limitations))
    return result


def load_score_config(path: str | Path) -> CompositeScoreConfig:
    """Load the versioned YAML policy without coupling analyzers to YAML."""
    try:
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("score configuration must be a YAML mapping")
        return CompositeScoreConfig.from_mapping(raw)
    except (OSError, ValueError, TypeError) as exc:
        log.error("invalid_score_configuration_file", path=str(path), error_type=type(exc).__name__)
        raise


__all__ = [
    "CANONICAL_DIMENSIONS",
    "DEFAULT_DIMENSION_WEIGHTS",
    "CompositeHealthScore",
    "CompositeScoreConfig",
    "ScoreContribution",
    "compose_health_score",
    "load_score_config",
]
