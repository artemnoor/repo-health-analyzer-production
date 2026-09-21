"""Activity calibration-v2 policy over normalized Git/PyDriller facts."""

from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime

from ...contracts.results import CategoryStatus, Confidence, Finding, HealthCategory, Limitation
from ...scoring.calibration_v2 import activity_score
from ..base import Analyzer, AnalyzerEvaluation
from .policy import POLICY_DIGEST


class ActivityAnalyzer(Analyzer):
    id = "repo-health.activity"
    version = "repo-health-activity-v1"
    category = HealthCategory.ACTIVITY
    fact_group = "git"
    policy_digest = POLICY_DIGEST
    negative_keys = ("stale_commit_count", "inactive_days")

    def evaluate(self, analyzer_input, observations: Mapping[str, object], evidence_id: str) -> AnalyzerEvaluation:
        if not observations:
            return AnalyzerEvaluation(score=None)

        def number(name: str, default: float | None = 0.0) -> float | None:
            value = observations.get(name, default)
            try:
                return None if value is None else float(value)
            except (TypeError, ValueError):
                return default

        commits = max(0.0, number("unique_commits", number("commit_count")) or 0.0)
        commits_90d = max(0.0, number("commits_90d", commits) or 0.0)
        authors = max(0.0, number("authors_90d", number("author_count")) or 0.0)
        empty = max(0.0, number("empty_commits") or 0.0)
        meaningful = number("meaningful_ratio", 1.0 if commits else 0.0)
        latest_age = number("latest_activity_age_days", None)
        if latest_age is None:
            raw_latest = observations.get("latest_activity_at")
            if isinstance(raw_latest, str):
                try:
                    timestamp = datetime.fromisoformat(raw_latest.replace("Z", "+00:00"))
                    reference = analyzer_input.facts.collected_at or datetime.now(UTC)
                    latest_age = max(0.0, (reference - timestamp.astimezone(UTC)).total_seconds() / 86400.0)
                except ValueError:
                    latest_age = None
        score, components = activity_score(
            unique_commits=commits,
            latest_age_days=latest_age,
            meaningful_ratio=meaningful,
            commits_90d=commits_90d,
            authors_90d=authors,
            empty_commits=empty,
        )
        if observations.get("activity_score") is not None:
            with suppress(TypeError, ValueError):
                score = max(0.0, min(100.0, float(observations["activity_score"])))
        limitations = []
        history_complete = observations.get("history_complete")
        if history_complete is False or observations.get("history_is_shallow") is True:
            limitations.append(
                Limitation(
                    code="git.shallow_history",
                    reason="Git history is shallow or capped; Activity is a lower bound",
                    affected_scope="activity",
                )
            )
        stale = number("inactive_days", 0.0) or 0.0
        findings = ()
        if stale >= 180:
            findings = (
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension="recency",
                    severity="medium",
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"Repository has had no measured activity for {stale:.0f} days",
                    evidence_ids=(evidence_id,),
                ),
            )
        status = (
            CategoryStatus.WARN
            if limitations or findings
            else CategoryStatus.PASS
            if score >= 80
            else CategoryStatus.WARN
            if score >= 50
            else CategoryStatus.FAIL
        )
        return AnalyzerEvaluation(
            score=score if commits > 0 or observations.get("activity_score") is not None else None,
            status=status,
            metrics={"activity_score": score, **components},
            findings=findings,
            limitations=tuple(limitations),
            coverage=observations.get("coverage"),
            confidence=observations.get("confidence"),
        )


__all__ = ["ActivityAnalyzer"]
