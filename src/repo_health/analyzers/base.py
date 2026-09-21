"""Shared analyzer lifecycle; category packages own only their policy/facts."""

from __future__ import annotations

import hashlib
from abc import ABC
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

import structlog

from ..contracts.results import (
    AnalyzerInput,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    Evidence,
    Finding,
    FindingLocation,
    HealthCategory,
    Limitation,
    Metric,
)

log = structlog.get_logger("repo_health.analyzers")


@dataclass(frozen=True, slots=True)
class AnalyzerEvaluation:
    """Category-local decision returned to the shared result composer."""

    score: float | None
    status: CategoryStatus | None = None
    metrics: Mapping[str, object] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    limitations: tuple[Limitation, ...] = ()
    coverage: float | None = None
    confidence: float | None = None
    score_signals: Mapping[str, int] = field(default_factory=dict)


def _bounded_ratio(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


class Analyzer(ABC):
    """Pure contract boundary shared by local and worker execution."""

    id: ClassVar[str]
    version: ClassVar[str]
    category: ClassVar[HealthCategory]
    fact_group: ClassVar[str]
    policy_digest: ClassVar[str]
    negative_keys: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def metadata(cls) -> dict[str, str]:
        return {
            "id": cls.id,
            "version": cls.version,
            "category": cls.category.value,
            "fact_group": cls.fact_group,
            "policy_digest": cls.policy_digest,
        }

    @classmethod
    def required_facts(cls) -> tuple[str, ...]:
        return (cls.fact_group,)

    def analyze(self, analyzer_input: AnalyzerInput) -> CategoryResult:
        if analyzer_input.analyzer_id != self.id:
            raise ValueError(f"AnalyzerInput ID {analyzer_input.analyzer_id!r} does not match {self.id!r}")
        if analyzer_input.analyzer_version != self.version:
            raise ValueError(
                f"AnalyzerInput version {analyzer_input.analyzer_version!r} does not match {self.version!r}"
            )
        started = datetime.now(UTC)
        group = getattr(analyzer_input.facts, self.fact_group)
        source_versions = dict(analyzer_input.facts.source_versions)
        if not group.available:
            limitation = Limitation(
                code=f"{self.fact_group}.unavailable", reason=f"{self.fact_group} facts are unavailable"
            )
            result = CategoryResult(
                analysis_id=analyzer_input.analysis_id,
                analyzer_id=self.id,
                analyzer_version=self.version,
                category=self.category,
                status=CategoryStatus.SKIPPED,
                coverage=Coverage(status="unavailable", reason=limitation.reason),
                confidence=Confidence(value=0.0, level="unknown", reason=limitation.reason),
                limitations=(*group.limitations, limitation),
                source_versions=source_versions,
            )
            log.info("analyzer_finished", **self._log_fields(analyzer_input, result, started))
            return result

        observations = {item.key: item.value for item in group.observations}
        evidence_id = f"{self.id}:facts:{analyzer_input.facts_digest[:24]}"
        evidence = Evidence(
            evidence_id=evidence_id,
            source=self.id,
            source_version=source_versions.get(self.fact_group),
            # A worker must reproduce the same serialized result from the same
            # facts.  Collection timestamps are part of the facts when known;
            # a missing timestamp uses a stable sentinel instead of wall time.
            collected_at=analyzer_input.facts.collected_at or datetime(1970, 1, 1, tzinfo=UTC),
            confidence=Confidence(value=1.0, level="high", reason="normalized fact block available"),
        )
        evaluation = self.evaluate(analyzer_input, observations, evidence_id)
        metrics_by_name = dict(evaluation.metrics)
        metrics_by_name.update(observations)
        metrics = tuple(
            Metric(
                name=key,
                value=value,
                score=float(value) if key.endswith("score") and _number(value) else None,
                evidence_ids=(evidence_id,),
            )
            for key, value in sorted(metrics_by_name.items())
            if _scalar(value)
        )
        coverage_value = _bounded_ratio(
            evaluation.coverage if evaluation.coverage is not None else observations.get("coverage"),
            default=1.0 if observations else 0.0,
        )
        confidence_value = _bounded_ratio(
            evaluation.confidence if evaluation.confidence is not None else observations.get("confidence"),
            default=coverage_value,
        )
        score = evaluation.score
        status = evaluation.status or (
            CategoryStatus.INCONCLUSIVE
            if score is None
            else CategoryStatus.PASS
            if score >= 80
            else CategoryStatus.WARN
            if score >= 50
            else CategoryStatus.FAIL
        )
        if evaluation.limitations and status is CategoryStatus.PASS:
            status = CategoryStatus.WARN
        result = CategoryResult(
            analysis_id=analyzer_input.analysis_id,
            analyzer_id=self.id,
            analyzer_version=self.version,
            category=self.category,
            status=status,
            score=score,
            metrics=metrics,
            findings=evaluation.findings,
            evidence=(evidence,),
            coverage=Coverage(
                status="complete" if coverage_value >= 1.0 else "available" if coverage_value > 0 else "partial",
                covered=len(observations),
                total=len(observations),
                reason=None,
            ),
            confidence=Confidence(
                value=confidence_value,
                level="high" if confidence_value >= 0.9 else "medium" if confidence_value >= 0.5 else "low",
            ),
            limitations=(*group.limitations, *evaluation.limitations),
            diagnostics_digest=hashlib.sha256(repr(sorted(observations.items())).encode()).hexdigest(),
            score_signals={**self._score_signals(observations, evaluation.findings), **dict(evaluation.score_signals)},
            source_versions=source_versions,
        )
        log.info("analyzer_finished", **self._log_fields(analyzer_input, result, started))
        return result

    def evaluate(
        self,
        analyzer_input: AnalyzerInput,
        observations: Mapping[str, object],
        evidence_id: str,
    ) -> AnalyzerEvaluation:
        """Apply the category policy to normalized scalar observations.

        Concrete categories override this hook.  The fallback intentionally
        retains support for an explicit upstream score while making no claim
        that an arbitrary observation set is a calibrated score.
        """

        findings = self._findings(analyzer_input, observations, evidence_id)
        return AnalyzerEvaluation(
            score=self._score(observations),
            findings=findings,
        )

    def _score(self, observations: Mapping[str, object]) -> float:
        explicit = next(
            (
                value
                for key, value in observations.items()
                if key in {"score", "health_score", f"{self.category.value}_score"} and _number(value) is not None
            ),
            None,
        )
        if explicit is not None:
            return max(0.0, min(100.0, float(explicit)))
        penalty = sum(
            max(0.0, float(observations[key]))
            for key in self.negative_keys
            if key in observations and _number(observations[key]) is not None
        )
        denominator = max(1.0, float(observations.get("denominator", 100) or 100))
        return max(0.0, min(100.0, 100.0 - min(100.0, (penalty / denominator) * 100.0)))

    def _findings(
        self, analyzer_input: AnalyzerInput, observations: Mapping[str, object], evidence_id: str
    ) -> tuple[Finding, ...]:
        rows: list[Finding] = []
        for key in self.negative_keys:
            value = observations.get(key)
            if not _number(value) or float(value) <= 0:
                continue
            severity = (
                "critical"
                if "critical" in key or "secret" in key
                else "high"
                if "error" in key or "high" in key
                else "medium"
            )
            rows.append(
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension=key,
                    severity=severity,
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"normalized facts report {value} {key.replace('_', ' ')}",
                    location=FindingLocation(),
                    evidence_ids=(evidence_id,),
                )
            )
        return tuple(rows)

    @staticmethod
    def _score_signals(observations: Mapping[str, object], findings: Iterable[Finding]) -> dict[str, int]:
        rows = tuple(findings)
        return {
            "active_findings": len(rows),
            "critical_findings": sum(item.severity == "critical" for item in rows),
            "high_findings": sum(item.severity == "high" for item in rows),
            "confirmed_secret_count": sum("secret" in item.dimension for item in rows),
        }

    @staticmethod
    def _log_fields(analyzer_input: AnalyzerInput, result: CategoryResult, started: datetime) -> dict[str, object]:
        return {
            "analysis_id": analyzer_input.analysis_id,
            "analyzer_id": result.analyzer_id,
            "facts_digest": analyzer_input.facts_digest,
            "policy_digest": analyzer_input.policy_digest,
            "status": result.status.value,
            "duration_ms": max(0, int((datetime.now(UTC) - started).total_seconds() * 1000)),
        }


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


__all__ = ["Analyzer", "AnalyzerEvaluation"]
