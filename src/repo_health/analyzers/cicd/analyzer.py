"""CI/CD calibration-v2 policy over normalized SourceCraft CI facts."""

from collections.abc import Mapping

from ...contracts.results import CategoryStatus, Confidence, Finding, HealthCategory, Limitation
from ...scoring.calibration_v2 import cicd_component_score
from ..base import Analyzer, AnalyzerEvaluation
from .policy import POLICY_DIGEST


class CicdAnalyzer(Analyzer):
    id = "repo-health.cicd"
    version = "repo-health-cicd-v1"
    category = HealthCategory.CICD
    fact_group = "cicd"
    policy_digest = POLICY_DIGEST
    negative_keys = ("failed_count", "failure_count", "broken_count")

    def evaluate(self, analyzer_input, observations: Mapping[str, object], evidence_id: str) -> AnalyzerEvaluation:
        if not observations:
            return AnalyzerEvaluation(score=None)

        def number(name: str, default: float | None = None) -> float | None:
            value = observations.get(name, default)
            try:
                return None if value is None else float(value)
            except (TypeError, ValueError):
                return default

        configured = observations.get("configured", True)
        if configured is False or str(configured).casefold() in {"false", "0", "not_configured"}:
            return AnalyzerEvaluation(
                score=None,
                status=CategoryStatus.SKIPPED,
                limitations=(
                    Limitation(
                        code="cicd.not_configured",
                        reason="CI/CD is not configured for this repository",
                        affected_scope="cicd",
                    ),
                ),
            )
        runs = int(max(0.0, number("decisive_runs", number("run_count", number("total_runs", 0.0))) or 0.0))
        if runs == 0 and observations.get("score") is None and observations.get("cicd_score") is None:
            return AnalyzerEvaluation(
                score=None,
                status=CategoryStatus.INCONCLUSIVE,
                limitations=(
                    Limitation(
                        code="cicd.no_runs", reason="CI/CD history contains no decisive runs", affected_scope="cicd"
                    ),
                ),
            )
        failure_rate = number("failure_rate")
        if failure_rate is not None and failure_rate > 1.0:
            failure_rate /= 100.0
        failure_streak = int(max(0.0, number("failure_streak", number("consecutive_failure_streak", 0.0)) or 0.0))
        p50 = number("p50_seconds", number("duration_p50_seconds"))
        p95 = number("p95_seconds", number("duration_p95_seconds"))
        failure_delta = number("failure_rate_delta")
        duration_delta = number("duration_delta")
        score, components, eligible = cicd_component_score(
            failure_rate=failure_rate,
            failure_streak=failure_streak,
            p50_seconds=p50,
            p95_seconds=p95,
            failure_rate_delta=failure_delta,
            duration_delta=duration_delta,
        )
        if score is None:
            explicit = number("cicd_score", number("score"))
            score = max(0.0, min(100.0, explicit)) if explicit is not None else None
        limitations = []
        if len(eligible) < 4 and score is not None:
            limitations.append(
                Limitation(
                    code="cicd.partial_components",
                    reason="CI/CD score uses only available calibration-v2 components",
                    affected_scope="cicd",
                )
            )
        findings: list[Finding] = []
        if failure_rate is not None and failure_rate >= 0.50:
            findings.append(
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension="reliability",
                    severity="critical",
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"CI/CD failure rate is {failure_rate:.1%}",
                    evidence_ids=(evidence_id,),
                )
            )
        elif failure_rate is not None and failure_rate >= 0.20:
            findings.append(
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension="reliability",
                    severity="high",
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"CI/CD failure rate is {failure_rate:.1%}",
                    evidence_ids=(evidence_id,),
                )
            )
        if failure_streak >= 5:
            findings.append(
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension="failure_streak",
                    severity="high",
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"CI/CD has a consecutive failure streak of {failure_streak}",
                    evidence_ids=(evidence_id,),
                )
            )
        status = (
            CategoryStatus.INCONCLUSIVE
            if score is None
            else CategoryStatus.FAIL
            if any(item.severity == "critical" for item in findings)
            else CategoryStatus.WARN
            if findings or limitations
            else CategoryStatus.PASS
            if score >= 80
            else CategoryStatus.WARN
            if score >= 50
            else CategoryStatus.FAIL
        )
        return AnalyzerEvaluation(
            score=score,
            status=status,
            metrics={"cicd_score": score, "failure_rate": failure_rate, "failure_streak": failure_streak, **components},
            findings=tuple(findings),
            limitations=tuple(limitations),
            coverage=observations.get("coverage"),
            confidence=observations.get("confidence"),
        )


__all__ = ["CicdAnalyzer"]
