"""SourceCraft AppSec REST policy over normalized severity facts."""

from collections.abc import Mapping
from contextlib import suppress

from ...contracts.results import AppSecScanState, CategoryStatus, Confidence, Finding, HealthCategory, Limitation
from ..base import Analyzer, AnalyzerEvaluation
from .policy import POLICY_DIGEST


class SecurityAnalyzer(Analyzer):
    id = "repo-health.security"
    version = "repo-health-security-v1"
    category = HealthCategory.SECURITY
    fact_group = "security"
    policy_digest = POLICY_DIGEST
    negative_keys = ("critical_count", "high_count", "secret_count", "active_count")

    def evaluate(self, analyzer_input, observations: Mapping[str, object], evidence_id: str) -> AnalyzerEvaluation:
        scan_state = analyzer_input.facts.security.scan_state
        if scan_state in {
            AppSecScanState.NO_SCAN,
            AppSecScanState.FAILED,
            AppSecScanState.UNAVAILABLE,
        }:
            reason_by_state = {
                AppSecScanState.NO_SCAN: "SourceCraft returned no AppSec scan for this repository",
                AppSecScanState.FAILED: "SourceCraft AppSec scan failed before findings were complete",
                AppSecScanState.UNAVAILABLE: "SourceCraft AppSec is unavailable for this repository",
            }
            return AnalyzerEvaluation(
                score=None,
                status=CategoryStatus.INCONCLUSIVE,
                limitations=(
                    Limitation(
                        code=f"appsec.{scan_state.value}",
                        reason=reason_by_state[scan_state],
                        affected_scope="security",
                    ),
                ),
                coverage=0.0,
                coverage_covered=0,
                coverage_total=1,
                coverage_reason=reason_by_state[scan_state],
                confidence=0.0,
                confidence_reason="No complete AppSec scan lifecycle evidence is available",
            )
        if not observations:
            return AnalyzerEvaluation(score=None)

        def count(*names: str) -> int:
            for name in names:
                value = observations.get(name)
                if value is not None:
                    try:
                        return max(0, int(float(value)))
                    except (TypeError, ValueError):
                        return 0
            return 0

        critical = count("critical_count", "critical_findings")
        high = count("high_count", "high_findings")
        medium = count("medium_count", "medium_findings")
        low = count("low_count", "low_findings")
        active = count("active_count", "active_findings")
        secrets = count("secret_count", "secret_findings", "confirmed_secret_count")
        has_measured_findings = any(
            name in observations
            for name in (
                "finding_count",
                "active_count",
                "active_findings",
                "critical_count",
                "critical_findings",
                "high_count",
                "high_findings",
                "medium_count",
                "medium_findings",
                "low_count",
                "low_findings",
            )
        )
        if scan_state is AppSecScanState.PARTIAL and not has_measured_findings:
            limitation = Limitation(
                code="appsec.partial",
                reason="AppSec lifecycle is partial and contains no measured findings",
                affected_scope="security",
            )
            return AnalyzerEvaluation(
                score=None,
                status=CategoryStatus.INCONCLUSIVE,
                limitations=(limitation,),
                coverage=0.0,
                coverage_covered=0,
                coverage_total=1,
                coverage_reason=limitation.reason,
                confidence=0.0,
                confidence_reason="No findings stage evidence is available",
            )
        if active == 0:
            active = critical + high + medium + low
        penalty = critical * 45.0 + high * 25.0 + medium * 10.0 + low * 3.0
        score = max(0.0, min(100.0, 100.0 - penalty))
        if scan_state is None and not any(
            name in observations
            for name in (
                "critical_count",
                "critical_findings",
                "high_count",
                "high_findings",
                "active_count",
                "active_findings",
                "score",
                "security_score",
            )
        ):
            return AnalyzerEvaluation(score=None)
        explicit = observations.get("security_score", observations.get("score"))
        if explicit is not None:
            with suppress(TypeError, ValueError):
                score = max(0.0, min(100.0, float(explicit)))
        findings: list[Finding] = []
        for dimension, value, severity in (
            ("secrets", secrets, "critical"),
            ("critical", critical, "critical"),
            ("high", high, "high"),
            ("medium", medium, "medium"),
            ("low", low, "low"),
        ):
            if value:
                findings.append(
                    Finding(
                        analyzer_id=self.id,
                        category=self.category,
                        dimension=dimension,
                        severity=severity,
                        confidence=Confidence(value=1.0, level="high"),
                        reason=f"SourceCraft AppSec reported {value} active {dimension} findings",
                        evidence_ids=(evidence_id,),
                    )
                )
        limitations: tuple[Limitation, ...] = ()
        if (
            scan_state is AppSecScanState.PARTIAL
            or observations.get("partial") is True
            or observations.get("groups_with_unavailable_findings")
        ):
            limitations = (
                Limitation(
                    code="appsec.partial", reason="Some AppSec groups were unavailable", affected_scope="security"
                ),
            )
        status = (
            CategoryStatus.FAIL
            if critical or secrets
            else CategoryStatus.WARN
            if high or active or limitations
            else CategoryStatus.PASS
        )
        metrics = {
            "security_score": score,
            "active_findings": active,
            "critical_findings": critical,
            "high_findings": high,
            "confirmed_secret_count": secrets,
        }
        if scan_state is not None:
            metrics["appsec_scan_state"] = scan_state.value
        return AnalyzerEvaluation(
            score=score,
            status=status,
            metrics=metrics,
            findings=tuple(findings),
            limitations=limitations,
            coverage=observations.get("coverage"),
            confidence=observations.get("confidence"),
            coverage_covered=1 if scan_state is not None else None,
            coverage_total=1 if scan_state is not None else None,
            coverage_reason=(
                "AppSec scan lifecycle completed"
                if scan_state is not AppSecScanState.PARTIAL
                else "AppSec scan completed with unavailable groups"
            )
            if scan_state is not None
            else None,
            confidence_reason=(
                "AppSec scan lifecycle evidence is complete"
                if scan_state is not AppSecScanState.PARTIAL
                else "AppSec scan has partial group coverage"
            )
            if scan_state is not None
            else None,
            score_signals={
                "active_findings": active,
                "critical_findings": critical,
                "high_findings": high,
                "confirmed_secret_count": secrets,
            },
        )


__all__ = ["SecurityAnalyzer"]
