"""Security category analyzer over normalized SourceCraft AppSec facts."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

import structlog

from .appsec_adapter import (
    APPSEC_SOURCE_COMMIT,
    AppSecDataStatus,
    AppSecFacts,
    SourceCraftAppSecAdapter,
    finding_evidence,
    finding_to_contract,
    stable_facts_ref,
)
from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Limitation,
    MetricValue,
)

log = structlog.get_logger("health.security.analyzer")

APPSEC_ANALYZER_ID = "sourcecraft.appsec"
APPSEC_DIMENSION = "security"
APPSEC_POLICY_REVISION = "sourcecraft-appsec-policy-v1"

APPSEC_DEFINITION = AnalyzerDefinition(
    id=APPSEC_ANALYZER_ID,
    version=APPSEC_POLICY_REVISION,
    category="security",
    dimensions=(APPSEC_DIMENSION,),
    requires=(),
    phase=60,
    cost=40,
    timeout=90,
    cache_policy="read_write",
    source_commit=APPSEC_SOURCE_COMMIT,
    enabled_by_mode=("backfill", "diff", "fast", "full", "offline"),
)

_PENALTIES = {
    "critical": 45.0,
    "high": 25.0,
    "medium": 10.0,
    "low": 3.0,
    "unknown": 10.0,
}


def _metric(name: str, value: float | int | str | bool | None, evidence: EvidenceRef, *, unit: str | None = None, population: int | None = None, denominator: int | None = None) -> MetricValue:
    return MetricValue(
        name=name,
        dimension=APPSEC_DIMENSION,
        value=value,
        unit=unit,
        population=population,
        denominator=denominator,
        evidence_refs=(evidence,),
    )


def _summary_evidence(context: AnalyzerContext, facts: AppSecFacts) -> EvidenceRef:
    return EvidenceRef(
        source="sourcecraft-appsec",
        source_commit=facts.source_version,
        json_pointer="/appsec",
        collected_at=context.as_of_ts,
        confidence=facts.confidence,
        redaction="partial",
    )


def _is_secret(item: Any) -> bool:
    engine = str(getattr(item, "engine", "") or "").casefold()
    rule = str(getattr(item, "rule", "") or "").casefold()
    return engine in {"gitleaks", "secret", "secrets"} or "secret" in rule


def analyze_appsec_facts(context: AnalyzerContext, facts: AppSecFacts) -> AnalyzerResult:
    started = datetime.now(UTC)
    summary_ref = _summary_evidence(context, facts)
    active = facts.active_findings
    severity_counts = Counter(item.severity for item in active)
    secret_count = sum(_is_secret(item) for item in active)
    penalty = sum(_PENALTIES.get(item.severity, _PENALTIES["unknown"]) for item in active)
    score = max(0.0, min(100.0, 100.0 - penalty))
    metrics = (
        _metric("appsec:scan_count", facts.scans_count, summary_ref, unit="scans", population=facts.scans_count, denominator=facts.scans_count),
        _metric("appsec:defect_group_count", facts.groups_count, summary_ref, unit="groups", population=facts.groups_count, denominator=facts.groups_count),
        _metric("appsec:active_findings", len(active), summary_ref, unit="findings", population=len(active), denominator=len(facts.findings)),
        _metric("appsec:critical_findings", severity_counts.get("critical", 0), summary_ref, unit="findings", population=severity_counts.get("critical", 0), denominator=len(active)),
        _metric("appsec:high_findings", severity_counts.get("high", 0), summary_ref, unit="findings", population=severity_counts.get("high", 0), denominator=len(active)),
        _metric("appsec:secret_findings", secret_count, summary_ref, unit="findings", population=secret_count, denominator=len(active)),
        _metric("appsec:coverage", facts.coverage, summary_ref, unit="ratio", population=facts.groups_count, denominator=facts.groups_count + facts.groups_with_unavailable_findings),
    )
    findings = tuple(finding_to_contract(context, facts, item) for item in active)
    evidence_rows = [summary_ref, *(finding_evidence(context, facts, item) for item in active)]
    evidence_by_json: dict[str, EvidenceRef] = {}
    for ref in evidence_rows:
        evidence_by_json.setdefault(ref.model_dump_json(), ref)
    limitations: list[Limitation] = []
    if facts.groups_with_unavailable_findings:
        limitations.append(Limitation(
            reason="Some SourceCraft AppSec defect groups or findings could not be read.",
            kind="missing_capability",
            affected_scope="security",
            evidence_refs=(summary_ref,),
        ))
    if facts.status is AppSecDataStatus.UNAVAILABLE:
        limitations.append(Limitation(reason="SourceCraft AppSec is unavailable for this repository.", kind="missing_capability", affected_scope="security"))
    if facts.status is AppSecDataStatus.ERROR:
        limitations.append(Limitation(reason="SourceCraft AppSec collection failed.", kind="error", affected_scope="security"))
    if facts.status is AppSecDataStatus.MEASURED and not active:
        limitations.append(Limitation(reason="No active AppSec findings were returned by SourceCraft.", kind="other", affected_scope="security"))

    if facts.status is AppSecDataStatus.UNAVAILABLE:
        status, final_score = AnalyzerStatus.SKIPPED, None
    elif facts.status is AppSecDataStatus.ERROR:
        status, final_score = AnalyzerStatus.ERROR, None
    elif any(item.severity == "critical" for item in active):
        status, final_score = AnalyzerStatus.FAIL, score
    elif active or facts.status is AppSecDataStatus.PARTIAL:
        status, final_score = AnalyzerStatus.WARN, score
    else:
        status, final_score = AnalyzerStatus.PASS, score

    diagnostics = {
        "security_status": facts.status.value,
        "appsec": facts.summary(),
        "active_severity_counts": dict(sorted(severity_counts.items())),
        "confirmed_secret_count": secret_count,
        "score_penalty": penalty,
        "score": final_score,
        "security_caps": {"high": 60.0, "critical": 40.0, "secret": 40.0},
        "enum_policy": "provider_status_mapping_is_defensive; unknown values remain UNKNOWN",
    }
    elapsed_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
    log.info(
        "appsec_analysis_finished",
        repo_id=context.repo_id,
        facts_status=facts.status.value,
        final_status=status.value,
        active_findings=len(active),
        score=round(final_score, 3) if final_score is not None else None,
        coverage=round(facts.coverage, 4),
        duration_ms=elapsed_ms,
    )
    return AnalyzerResult(
        analyzer_id=APPSEC_ANALYZER_ID,
        analyzer_version=APPSEC_POLICY_REVISION,
        status=status,
        score=final_score,
        score_dimension=APPSEC_DIMENSION if final_score is not None else None,
        metrics=metrics,
        findings=findings,
        evidence=tuple(evidence_by_json.values()),
        limitations=tuple(limitations),
        duration_ms=elapsed_ms,
        source_versions={
            "sourcecraft_appsec": facts.source_version,
            "appsec_policy": APPSEC_POLICY_REVISION,
        },
        available_weight=1.0 if final_score is not None else 0.0,
        total_weight=1.0,
        raw_payload_ref=stable_facts_ref(facts),
        diagnostics=diagnostics,
    )


class AppSecAnalyzer:
    def __init__(self, *, adapter: SourceCraftAppSecAdapter | None = None) -> None:
        self.adapter = adapter or SourceCraftAppSecAdapter()

    def run(self, context: AnalyzerContext) -> AnalyzerResult:
        return analyze_appsec_facts(context, self.adapter.collect(context))


def appsec_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return AppSecAnalyzer().run(context)


def register_appsec_adapter(registry: Any) -> None:
    if APPSEC_DEFINITION.id not in registry.ids():
        registry.register(APPSEC_DEFINITION, appsec_adapter)


__all__ = [
    "APPSEC_ANALYZER_ID",
    "APPSEC_DEFINITION",
    "APPSEC_DIMENSION",
    "APPSEC_POLICY_REVISION",
    "AppSecAnalyzer",
    "analyze_appsec_facts",
    "appsec_adapter",
    "register_appsec_adapter",
]
