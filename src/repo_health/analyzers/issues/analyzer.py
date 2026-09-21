"""Issues partial-component policy over normalized SourceCraft facts."""

from collections.abc import Mapping

from ...contracts.results import CategoryStatus, Confidence, Finding, HealthCategory, Limitation
from ..base import Analyzer, AnalyzerEvaluation
from .policy import POLICY_DIGEST


class IssuesAnalyzer(Analyzer):
    id = "repo-health.issues"
    version = "repo-health-issues-v1"
    category = HealthCategory.ISSUES
    fact_group = "issues"
    policy_digest = POLICY_DIGEST
    negative_keys = ("stale_count", "unanswered_count", "slow_close_count")

    @staticmethod
    def _quality(value: float | None, target: float, breach: float) -> float | None:
        if value is None:
            return None
        if value <= target:
            return 1.0
        if value >= breach:
            return 0.0
        return max(0.0, min(1.0, (breach - value) / (breach - target)))

    def evaluate(self, analyzer_input, observations: Mapping[str, object], evidence_id: str) -> AnalyzerEvaluation:
        if not observations:
            return AnalyzerEvaluation(score=None)

        def number(name: str, default: float | None = None) -> float | None:
            value = observations.get(name, default)
            try:
                return None if value is None else float(value)
            except (TypeError, ValueError):
                return default

        sample = int(max(0.0, number("sample_size", number("issue_count", number("open_count", 0.0))) or 0.0))
        coverage = number("coverage", 1.0 if sample else 0.0) or 0.0
        comments_available = observations.get("comments_available")
        if comments_available is None:
            comments_available = any(
                key in observations for key in ("answered_count", "unanswered_count", "response_median_hours")
            )
        comments_available = bool(comments_available)
        limitations: list[Limitation] = []
        components: dict[str, float] = {}
        component_coverage: dict[str, float] = {}

        answered = number("answered_count")
        unanswered = number("unanswered_count")
        if answered is None and unanswered is not None:
            answered = max(0.0, sample - unanswered)
        response_median = number("response_median_hours", number("first_response_median_hours"))
        response_p75 = number("response_p75_hours", number("first_response_p75_hours", response_median))
        response_eligible = (
            comments_available
            and sample >= 5
            and coverage >= 0.80
            and answered is not None
            and response_median is not None
        )
        if response_eligible:
            latency = 0.5 * (self._quality(response_median, 72.0, 360.0) or 0.0) + 0.5 * (
                self._quality(response_p75, 168.0, 720.0) or 0.0
            )
            components["responsiveness"] = 100.0 * min(1.0, answered / max(sample, 1)) * latency
            component_coverage["responsiveness"] = coverage
        elif not comments_available and sample >= 5:
            limitations.append(
                Limitation(
                    code="issues.comments_unavailable",
                    reason="Human response metrics are unavailable because comments are not complete",
                    affected_scope="responsiveness",
                )
            )

        mature = int(max(0.0, number("mature_count", number("closed_count", 0.0)) or 0.0))
        closed = number("closed_count")
        close_median = number("close_median_hours", number("time_to_close_median_hours"))
        close_p75 = number("close_p75_hours", number("time_to_close_p75_hours", close_median))
        resolution_eligible = mature >= 5 and coverage >= 0.50 and closed is not None and close_median is not None
        if resolution_eligible:
            latency = 0.5 * (self._quality(close_median, 360.0, 1440.0) or 0.0) + 0.5 * (
                self._quality(close_p75, 720.0, 2160.0) or 0.0
            )
            components["resolution"] = 100.0 * min(1.0, closed / max(mature, 1)) * latency
            component_coverage["resolution"] = coverage

        open_count = int(max(0.0, number("open_count", 0.0) or 0.0))
        open_age_p75 = number("open_age_p75_hours", number("oldest_open_age_hours"))
        stale_ratio = number("stale_ratio")
        backlog_eligible = sample >= 5 and coverage >= 0.50 and open_age_p75 is not None
        if backlog_eligible:
            age_quality = self._quality(open_age_p75, 720.0, 2160.0) or 0.0
            if open_count == 0:
                components["backlog_health"] = 50.0
            else:
                components["backlog_health"] = 100.0 * (0.60 * (1.0 - (stale_ratio or 0.0)) + 0.40 * age_quality)
            component_coverage["backlog_health"] = coverage

        created = number("trend_created")
        closed_trend = number("trend_closed")
        trend_total = int(max(0.0, (created or 0.0) + (closed_trend or 0.0)))
        if trend_total >= 5 and coverage >= 0.50:
            components["maintenance_trend"] = 100.0 * (closed_trend or 0.0) / trend_total
            component_coverage["maintenance_trend"] = coverage

        if len(components) >= 2 and any(name in components for name in ("resolution", "backlog_health")):
            weights = {"responsiveness": 0.30, "resolution": 0.30, "backlog_health": 0.25, "maintenance_trend": 0.15}
            total = sum(weights[name] for name in components)
            score = sum(components[name] * weights[name] for name in components) / total
        else:
            explicit = number("issues_score", number("score"))
            # A repository count without lifecycle/comment fields is still a
            # valid normalized baseline fact, but it cannot activate the
            # partial-component policy. Keep the historical neutral baseline
            # until a richer SourceCraft snapshot is available.
            score = (
                max(0.0, min(100.0, explicit))
                if explicit is not None
                else 100.0
                if any(key in observations for key in ("open_count", "closed_count", "issue_count"))
                else None
            )

        findings: list[Finding] = []
        stale_count = int(max(0.0, number("stale_count", number("stale_open_issues", 0.0)) or 0.0))
        unanswered_count = int(max(0.0, number("unanswered_count", 0.0) or 0.0))
        slow_close = int(max(0.0, number("slow_close_count", 0.0) or 0.0))
        for dimension, count, severity, reason in (
            ("stale_backlog", stale_count, "medium", "stale open issues were reported"),
            ("unanswered", unanswered_count, "medium", "issues without a qualifying human response were reported"),
            ("slow_close", slow_close, "high", "issues exceeding the close-time policy were reported"),
        ):
            if count:
                findings.append(
                    Finding(
                        analyzer_id=self.id,
                        category=self.category,
                        dimension=dimension,
                        severity=severity,
                        confidence=Confidence(
                            value=max(0.0, min(1.0, coverage)), level="high" if coverage >= 0.8 else "medium"
                        ),
                        reason=f"{count} {reason}",
                        evidence_ids=(evidence_id,),
                    )
                )
        if score is None:
            status = CategoryStatus.INCONCLUSIVE
        elif findings or limitations:
            status = CategoryStatus.WARN
        else:
            status = CategoryStatus.PASS if score >= 80 else CategoryStatus.WARN if score >= 50 else CategoryStatus.FAIL
        return AnalyzerEvaluation(
            score=score,
            status=status,
            metrics={
                "issues_score": score,
                **components,
                **{f"{name}_coverage": value for name, value in component_coverage.items()},
            },
            findings=tuple(findings),
            limitations=tuple(limitations),
            coverage=coverage,
            confidence=number("confidence", coverage),
        )


__all__ = ["IssuesAnalyzer"]
