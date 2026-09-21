"""Documentation category policy over normalized Vale facts."""

from collections.abc import Mapping
from contextlib import suppress

from ...contracts.results import CategoryStatus, Confidence, Finding, HealthCategory, Limitation
from ...scoring.calibration_v2 import documentation_quality, documentation_score
from ..base import Analyzer, AnalyzerEvaluation
from .policy import POLICY_DIGEST


class DocumentationAnalyzer(Analyzer):
    id = "repo-health.documentation"
    version = "repo-health-documentation-v1"
    category = HealthCategory.DOCUMENTATION
    fact_group = "documentation"
    policy_digest = POLICY_DIGEST
    negative_keys = ("error_count", "finding_count")

    def evaluate(self, analyzer_input, observations: Mapping[str, object], evidence_id: str) -> AnalyzerEvaluation:
        if not observations:
            return AnalyzerEvaluation(score=None)

        def number(name: str, default: float = 0.0) -> float:
            value = observations.get(name, default)
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                return default

        file_count = number("analyzed_files", number("file_count"))
        discovered = number("discovered_files", file_count)
        words = number("words")
        finding_points = number("weighted_finding_points")
        if finding_points == 0.0:
            finding_points = (
                number("suggestion_count") * 0.25
                + number("warning_count")
                + number("error_count") * 2.0
                + number("fatal_count") * 3.0
            )
        vale_quality = observations.get("vale_quality")
        try:
            quality = max(0.0, min(100.0, float(vale_quality)))
        except (TypeError, ValueError):
            quality, _density = documentation_quality(finding_points=finding_points, words=words)
        completeness = number("completeness", 100.0 if file_count else 0.0)
        instructions = number("instructions", 100.0 if observations.get("has_instructions") else 0.0)
        readability = number("readability", 100.0)
        if readability == 100.0 and words:
            complex_words = number("complex_words")
            long_words = number("long_words")
            readability = max(
                0.0, 100.0 - 100.0 * complex_words / max(words, 1.0) - 60.0 * long_words / max(words, 1.0)
            )
        score = documentation_score(
            completeness=completeness,
            instructions=instructions,
            vale_quality=quality,
            readability=readability,
        )
        if observations.get("documentation_score") is not None:
            with suppress(TypeError, ValueError):
                score = max(0.0, min(100.0, float(observations["documentation_score"])))
        findings = []
        error_count = int(number("error_count"))
        finding_count = int(number("finding_count"))
        if error_count:
            findings.append(
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension="vale_errors",
                    severity="high",
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"Vale reported {error_count} error-level documentation findings",
                    evidence_ids=(evidence_id,),
                )
            )
        elif finding_count:
            findings.append(
                Finding(
                    analyzer_id=self.id,
                    category=self.category,
                    dimension="vale_findings",
                    severity="medium",
                    confidence=Confidence(value=1.0, level="high"),
                    reason=f"Vale reported {finding_count} documentation findings",
                    evidence_ids=(evidence_id,),
                )
            )
        limitations = []
        coverage = observations.get("coverage")
        if coverage is None and discovered:
            coverage = file_count / discovered
        if discovered and file_count < discovered:
            limitations.append(
                Limitation(
                    code="vale.partial",
                    reason="Vale analyzed only part of the discovered documentation",
                    affected_scope="documentation",
                )
            )
        status = (
            CategoryStatus.FAIL
            if error_count
            else CategoryStatus.WARN
            if findings or limitations
            else CategoryStatus.PASS
        )
        return AnalyzerEvaluation(
            score=score if file_count or observations.get("documentation_score") is not None else None,
            status=status,
            metrics={
                "documentation_score": score,
                "vale_quality": quality,
                "completeness": completeness,
                "instructions": instructions,
                "readability": readability,
                "finding_points": finding_points,
            },
            findings=tuple(findings),
            limitations=tuple(limitations),
            coverage=coverage,
            confidence=observations.get("confidence", observations.get("metrics_coverage")),
        )


__all__ = ["DocumentationAnalyzer"]
