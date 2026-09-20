"""Production CI/CD analyzer over normalized SourceCraft facts."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any

import structlog

from ..calibration_policy_v2 import cicd_component_score
from .cicd_adapter import SourceCraftCICDAdapter
from .cicd_facts import (
    CICD_POLICY_REVISION,
    CICD_SOURCE_COMMIT,
    CICDDataStatus,
    CICDFacts,
    CICDPolicy,
    CICDRunFact,
    CICDRunStatus,
    CICDWindowFacts,
    load_cicd_policy,
)
from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    MetricValue,
)

log = structlog.get_logger("cicd.analyzer")

CICD_ANALYZER_ID = "cicd.sourcecraft"
CICD_DIMENSION = "delivery"


def _definition_version() -> str:
    try:
        policy = load_cicd_policy()
        return f"{policy.policy_revision}-{policy.digest[:12]}"
    except (OSError, TypeError, ValueError):
        return CICD_POLICY_REVISION


CICD_DEFINITION = AnalyzerDefinition(
    id=CICD_ANALYZER_ID,
    version=_definition_version(),
    category="cicd",
    dimensions=(CICD_DIMENSION,),
    requires=(),
    phase=60,
    cost=35,
    timeout=60,
    # The current checkout has no pre-cache SourceCraft collector hook. Keep
    # CI results uncached until source_snapshot_digest is folded into the
    # health-edge cache context.
    cache_policy="none",
    source_commit=CICD_SOURCE_COMMIT,
    enabled_by_mode=("backfill", "diff", "fast", "full", "offline"),
)


def _bounded(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _evidence(context: AnalyzerContext, facts: CICDFacts) -> EvidenceRef:
    return EvidenceRef(
        source="sourcecraft",
        source_commit=facts.source_version or CICD_SOURCE_COMMIT,
        tool_version=facts.source_version,
        json_pointer="/sourcecraft_cicd",
        collected_at=context.as_of_ts,
        confidence=facts.confidence,
        redaction="partial",
    )


def _run_evidence(context: AnalyzerContext, facts: CICDFacts, run: CICDRunFact) -> EvidenceRef:
    return EvidenceRef(
        source="sourcecraft",
        source_commit=facts.source_version or CICD_SOURCE_COMMIT,
        tool_version=facts.source_version,
        json_pointer=run.source_json_pointer or f"/runs/{run.run_id}",
        collected_at=context.as_of_ts,
        confidence=facts.confidence,
        redaction="partial",
    )


def _metric(
    name: str,
    value: float | int | str | bool | None,
    evidence: EvidenceRef,
    *,
    unit: str | None = None,
    population: int | None = None,
    denominator: int | None = None,
) -> MetricValue:
    return MetricValue(
        name=name,
        dimension=CICD_DIMENSION,
        value=value,
        unit=unit,
        population=population,
        denominator=denominator,
        evidence_refs=(evidence,),
    )


def _unique_refs(refs: tuple[EvidenceRef, ...] | list[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    seen: dict[str, EvidenceRef] = {}
    for ref in refs:
        seen.setdefault(ref.model_dump_json(), ref)
    return tuple(seen.values())


def _unique_limitations(limitations: tuple[Limitation, ...] | list[Limitation]) -> tuple[Limitation, ...]:
    seen: dict[str, Limitation] = {}
    for limitation in limitations:
        seen.setdefault(limitation.model_dump_json(), limitation)
    return tuple(seen.values())


def _window(facts: CICDFacts, name: str) -> CICDWindowFacts | None:
    return next((item for item in facts.windows if item.name == name), None)


def _overall_rates(facts: CICDFacts) -> tuple[float | None, float | None, float | None]:
    terminal = facts.terminal_runs
    decisive = facts.decisive_runs
    if not terminal:
        return None, None, None
    success = sum(run.status is CICDRunStatus.SUCCESS for run in decisive)
    failure = sum(run.status is CICDRunStatus.FAILURE for run in decisive)
    return (
        success / len(decisive) if decisive else None,
        failure / len(decisive) if decisive else None,
        len(decisive) / len(terminal),
    )


def _dora_statuses(facts: CICDFacts) -> dict[str, str]:
    required = {
        "deployment_frequency": ("deployment_events", "production_environment"),
        "lead_time_for_changes": ("deployment_events", "deployment_commits"),
        "change_failure_rate": ("deployment_events", "production_environment"),
        "time_to_restore": ("incidents", "restore_events"),
    }
    result: dict[str, str] = {}
    for metric, capabilities in required.items():
        values = [str(facts.dora_capabilities.get(key, "absent")).lower() for key in capabilities]
        if any(value in {"absent", "false", "unsupported", "not_available"} for value in values):
            result[metric] = "NOT_APPLICABLE"
        elif all(value in {"present", "true", "measured"} for value in values):
            result[metric] = "UNAVAILABLE"
        else:
            result[metric] = "NOT_APPLICABLE"
    return result


def _trend_values(
    current: CICDWindowFacts | None,
    previous: CICDWindowFacts | None,
    policy: CICDPolicy,
) -> tuple[float | None, float | None, str]:
    if current is None or previous is None:
        return None, None, "unavailable"
    failure_delta = (
        current.failure_rate - previous.failure_rate
        if current.failure_rate is not None and previous.failure_rate is not None
        else None
    )
    duration_delta = (
        (current.p50_seconds - previous.p50_seconds) / previous.p50_seconds
        if current.p50_seconds is not None
        and previous.p50_seconds is not None
        and previous.p50_seconds > 0
        else None
    )
    if (
        current.terminal_runs < policy.minimum_trend_runs_per_period
        or previous.terminal_runs < policy.minimum_trend_runs_per_period
        or current.decisive_runs < policy.minimum_trend_runs_per_period
        or previous.decisive_runs < policy.minimum_trend_runs_per_period
    ):
        return failure_delta, duration_delta, "unavailable"
    signals: list[float] = []
    if failure_delta is not None:
        signals.append(failure_delta / policy.failure_trend_scale)
    if duration_delta is not None:
        signals.append(duration_delta / policy.duration_trend_scale)
    if not signals:
        return failure_delta, duration_delta, "unavailable"
    mean_signal = sum(signals) / len(signals)
    if mean_signal <= -0.20:
        label = "improving"
    elif mean_signal >= 0.20:
        label = "worsening"
    else:
        label = "flat"
    return failure_delta, duration_delta, label


def _finding(
    analyzer_id: str,
    subject: str,
    severity: str,
    reason: str,
    confidence: float,
    evidence: EvidenceRef | tuple[EvidenceRef, ...],
    *,
    location: FindingLocation | None = None,
) -> Finding:
    return Finding(
        id=f"{analyzer_id}:{subject}",
        analyzer_id=analyzer_id,
        subject=subject,
        dimension=CICD_DIMENSION,
        severity=severity,  # type: ignore[arg-type]
        confidence=_bounded(confidence),
        reason=reason,
        evidence_refs=evidence if isinstance(evidence, tuple) else (evidence,),
        location=location,
        remediation="Review the SourceCraft CI workflow and its recent run history.",
    )


def _analysis(
    context: AnalyzerContext,
    facts: CICDFacts,
    policy: CICDPolicy,
) -> tuple[
    tuple[MetricValue, ...],
    tuple[Finding, ...],
    tuple[Limitation, ...],
    float | None,
    dict[str, Any],
]:
    evidence = _evidence(context, facts)
    metrics: list[MetricValue] = []
    findings: list[Finding] = []
    limitations = [
        Limitation(
            reason=reason.replace("_", " "),
            kind="insufficient_denominator" if "insufficient" in reason or "pagination" in reason else "missing_capability" if "missing" in reason else "other",
            affected_scope="cicd",
            evidence_refs=(evidence,),
        )
        for reason in facts.limitations
    ]
    total = len(facts.runs)
    terminal = facts.terminal_runs
    decisive = facts.decisive_runs
    success_rate, failure_rate, completion_health = _overall_rates(facts)
    count_by_status = {
        status.value: sum(run.status is status for run in facts.runs)
        for status in CICDRunStatus
    }
    metric_rows: list[tuple[str, object, str | None, int | None, int | None]] = [
        ("configured", facts.configured, None, 1, 1),
        ("total_runs", total, "runs", total, 1 if total else 0),
        ("terminal_runs", len(terminal), "runs", len(terminal), 1 if terminal else 0),
        ("decisive_runs", len(decisive), "runs", len(decisive), 1 if decisive else 0),
        ("success_runs", count_by_status[CICDRunStatus.SUCCESS.value], "runs", len(terminal), len(terminal)),
        ("failure_runs", count_by_status[CICDRunStatus.FAILURE.value], "runs", len(terminal), len(terminal)),
        ("cancelled_runs", count_by_status[CICDRunStatus.CANCELLED.value], "runs", len(terminal), len(terminal)),
        ("skipped_runs", count_by_status[CICDRunStatus.SKIPPED.value], "runs", len(terminal), len(terminal)),
        ("rejected_runs", count_by_status[CICDRunStatus.REJECTED.value], "runs", len(terminal), len(terminal)),
        ("in_progress_runs", count_by_status[CICDRunStatus.IN_PROGRESS.value], "runs", total, total),
        ("unknown_status_runs", count_by_status[CICDRunStatus.UNKNOWN.value], "runs", total, total),
        ("success_rate", success_rate, "ratio", len(decisive), len(decisive)),
        ("failure_rate", failure_rate, "ratio", len(decisive), len(decisive)),
        (
            "non_decisive_rate",
            (len(terminal) - len(decisive)) / len(terminal) if terminal else None,
            "ratio",
            len(terminal),
            len(terminal),
        ),
        ("completion_health", completion_health, "ratio", len(terminal), len(terminal)),
        ("last_run_status", facts.latest_observed.status.value if facts.latest_observed else None, None, 1, 1 if facts.latest_observed else 0),
        ("last_run_at", _iso(facts.latest_observed.updated_at if facts.latest_observed else None), None, 1, 1 if facts.latest_observed else 0),
        ("last_terminal_status", facts.latest_terminal.status.value if facts.latest_terminal else None, None, 1, 1 if facts.latest_terminal else 0),
        ("last_terminal_at", _iso(facts.latest_terminal.finished_at if facts.latest_terminal else None), None, 1, 1 if facts.latest_terminal else 0),
        ("last_success_at", _iso(facts.latest_successful.finished_at if facts.latest_successful else None), None, 1, 1 if facts.latest_successful else 0),
        ("consecutive_failure_streak", facts.consecutive_failure_streak, "runs", len(terminal), len(terminal)),
        ("coverage", facts.coverage, "ratio", 1, 1),
        ("confidence", facts.confidence, "ratio", 1, 1),
        ("retry_count", len(facts.retry_relations), "runs", len(facts.runs), len(facts.runs)),
        ("rerun_group_count", len({relation.relation_key for relation in facts.retry_relations}), "groups", len(facts.retry_relations), len(facts.retry_relations)),
        ("flaky_failure_to_success_count", len(facts.retry_relations), "runs", len(facts.retry_relations), len(facts.retry_relations)),
    ]
    for name, value, unit, population, denominator in metric_rows:
        metrics.append(_metric(f"cicd:{name}", value, evidence, unit=unit, population=population, denominator=denominator))

    for window in facts.windows:
        prefix = f"cicd:{window.name}"
        for name, value, unit, population, denominator in (
            ("total_runs", window.total_runs, "runs", window.total_runs, 1 if window.total_runs else 0),
            ("terminal_runs", window.terminal_runs, "runs", window.terminal_runs, 1 if window.terminal_runs else 0),
            ("decisive_runs", window.decisive_runs, "runs", window.decisive_runs, 1 if window.decisive_runs else 0),
            ("success_rate", window.success_rate, "ratio", window.decisive_runs, window.decisive_runs),
            ("failure_rate", window.failure_rate, "ratio", window.decisive_runs, window.decisive_runs),
            ("duration_p50_seconds", window.p50_seconds, "seconds", len(window.durations), len(window.durations)),
            ("duration_p95_seconds", window.p95_seconds, "seconds", len(window.durations), len(window.durations)),
            ("duration_sample_size", len(window.durations), "runs", len(window.durations), 1 if window.durations else 0),
            ("failure_streak", window.failure_streak, "runs", window.terminal_runs, window.terminal_runs),
        ):
            metrics.append(_metric(f"{prefix}:{name}", value, evidence, unit=unit, population=population, denominator=denominator))

    current = _window(facts, "current")
    previous = _window(facts, "previous")
    failure_delta, duration_delta, trend_label = _trend_values(current, previous, policy)
    metrics.extend(
        (
            _metric("cicd:duration_delta_p50_percent", duration_delta, evidence, unit="ratio", population=1, denominator=1 if duration_delta is not None else 0),
            _metric("cicd:stability_trend", trend_label, evidence, population=1, denominator=1 if trend_label != "unavailable" else 0),
            _metric("cicd:failure_rate_delta", failure_delta, evidence, unit="ratio", population=1, denominator=1 if failure_delta is not None else 0),
            _metric("cicd:pagination_complete", facts.pagination_complete, evidence, population=1, denominator=1 if facts.pagination_complete is not None else 0),
            _metric("cicd:pages_fetched", facts.pages_fetched, evidence, unit="pages", population=facts.pages_fetched, denominator=1 if facts.pages_fetched else 0),
        )
    )

    dora_statuses = _dora_statuses(facts)
    for name, status in dora_statuses.items():
        metrics.append(_metric(f"dora:{name}:status", status, evidence, population=1, denominator=1))
    dora_limitations = tuple(
        Limitation(
            reason=f"DORA {name} is {status}; no deployment/environment/incident data was supplied.",
            kind="unsupported" if status == "NOT_APPLICABLE" else "missing_capability",
            affected_scope=f"dora:{name}",
            evidence_refs=(evidence,),
        )
        for name, status in dora_statuses.items()
    )
    limitations.extend(dora_limitations)

    durations = tuple(run.duration_seconds for run in terminal if run.duration_seconds is not None)
    if len(durations) >= policy.minimum_duration_runs:
        p50 = current.p50_seconds if current and current.p50_seconds is not None else sorted(durations)[(len(durations) - 1) // 2]
        p95 = current.p95_seconds if current and current.p95_seconds is not None else max(durations)
    else:
        p50 = None
        p95 = None

    score, component_scores, eligible = cicd_component_score(
        failure_rate=failure_rate if len(decisive) >= policy.minimum_decisive_runs else None,
        failure_streak=facts.consecutive_failure_streak if len(terminal) >= policy.minimum_terminal_runs else 0,
        p50_seconds=p50,
        p95_seconds=p95,
        failure_rate_delta=failure_delta if trend_label != "unavailable" else None,
        duration_delta=duration_delta if trend_label != "unavailable" else None,
    )
    component_coverage = {name: facts.coverage for name in eligible}
    weights = {
        "reliability": policy.reliability_weight,
        "failure_streak": policy.failure_streak_weight,
        "duration": policy.duration_weight,
        "trend": policy.trend_weight,
    }

    if facts.status in {CICDDataStatus.MEASURED, CICDDataStatus.PARTIAL}:
        if failure_rate is not None and failure_rate >= policy.failure_warning_rate:
            severity = "critical" if failure_rate >= policy.failure_critical_rate else "high"
            failed_runs = tuple(
                run for run in decisive if run.status is CICDRunStatus.FAILURE
            )
            failure_evidence = tuple(
                _run_evidence(context, facts, run)
                for run in failed_runs[: policy.maximum_findings]
            )
            findings.append(
                _finding(
                    CICD_ANALYZER_ID,
                    "failure-rate",
                    severity,
                    f"CI failure rate is {failure_rate:.1%} over {len(decisive)} decisive runs.",
                    facts.confidence,
                    failure_evidence or evidence,
                )
            )
        if facts.consecutive_failure_streak >= policy.warning_streak:
            severity = "critical" if facts.consecutive_failure_streak >= policy.critical_streak else "high"
            streak_run = facts.latest_terminal
            findings.append(
                _finding(
                    CICD_ANALYZER_ID,
                    "failure-streak",
                    severity,
                    f"CI has a consecutive failure streak of {facts.consecutive_failure_streak}.",
                    facts.confidence,
                    _run_evidence(context, facts, streak_run) if streak_run else evidence,
                )
            )
        if trend_label == "worsening":
            findings.append(
                _finding(
                    CICD_ANALYZER_ID,
                    "worsening-trend",
                    "medium",
                    "Current CI stability is worsening versus the previous period.",
                    facts.confidence,
                    evidence,
                )
            )
        if facts.retry_relations:
            relation = facts.retry_relations[0]
            failed = next((run for run in facts.runs if run.run_id == relation.failed_run_id), None)
            findings.append(
                _finding(
                    CICD_ANALYZER_ID,
                    "proven-flaky-run",
                    "medium",
                    f"Run {relation.failed_run_id} failed and linked rerun {relation.successful_run_id} later succeeded.",
                    facts.confidence,
                    _run_evidence(context, facts, failed) if failed else evidence,
                )
            )
        if terminal and (len(terminal) - len(decisive)) / len(terminal) > 0.50:
            findings.append(
                _finding(
                    CICD_ANALYZER_ID,
                    "non-decisive-runs",
                    "medium",
                    "More than half of terminal CI runs were cancelled, skipped, or rejected.",
                    facts.confidence,
                    evidence,
                )
            )

    findings.sort(key=lambda item: ({"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[item.severity], item.id))
    findings = findings[: policy.maximum_findings]
    diagnostics = {
        "component_scores": component_scores,
        "component_coverage": component_coverage,
        "eligible_components": tuple(sorted(eligible)),
        "raw_score": (
            sum(component_scores[name] * weights[name] for name in eligible) / sum(weights[name] for name in eligible)
            if eligible and sum(weights[name] for name in eligible)
            else None
        ),
        "confidence_multiplier": 1.0,
        "score_formula": "0.75*reliability+0.15*failure_streak+0.05*duration+0.05*trend; unavailable components reweighted",
        "dora_statuses": dora_statuses,
        "double_count_guard": "one_aggregate_cicd_score_delivery",
        "problem_runs": tuple(
            {
                "run_id": run.run_id,
                "workflow_id": run.workflow_id,
                "workflow_name": run.workflow_name,
                "status": run.status.value,
                "failure_kind": run.failure_kind,
                "duration_seconds": run.duration_seconds,
                "finished_at": _iso(run.finished_at),
                "deep_link": run.deep_link,
            }
            for run in facts.runs
            if run.status is CICDRunStatus.FAILURE
        ),
        "retry_relations": tuple(
            {
                "failed_run_id": relation.failed_run_id,
                "successful_run_id": relation.successful_run_id,
                "relation_key": relation.relation_key,
                "workflow_key": relation.workflow_key,
                "commit_sha": relation.commit_sha,
            }
            for relation in facts.retry_relations
        ),
    }
    return tuple(metrics), tuple(findings), _unique_limitations(limitations), score, diagnostics


class CICDAnalyzer:
    """Analyze normalized CI/CD facts and return one delivery result."""

    def __init__(
        self,
        *,
        adapter: SourceCraftCICDAdapter | None = None,
        policy_loader: Any = load_cicd_policy,
    ) -> None:
        self.adapter = adapter or SourceCraftCICDAdapter()
        self.policy_loader = policy_loader

    def run(self, context: AnalyzerContext) -> AnalyzerResult:
        started = datetime.now(UTC)
        try:
            policy = self.policy_loader()
            facts = self.adapter.collect(context, policy=policy)
        except (OSError, TypeError, ValueError, ImportError) as exc:
            log.error(
                "cicd_policy_or_collection_failed",
                repo_id=context.repo_id,
                failure_kind=type(exc).__name__,
            )
            return AnalyzerResult(
                analyzer_id=CICD_ANALYZER_ID,
                analyzer_version=CICD_DEFINITION.version,
                status=AnalyzerStatus.ERROR,
                limitations=(Limitation(reason="CI/CD policy or normalization failed", kind="error"),),
                diagnostics={"cicd_status": CICDDataStatus.ERROR.value, "error_type": type(exc).__name__},
            )
        return self.analyze(context, facts, policy=policy, started=started)

    def analyze(
        self,
        context: AnalyzerContext,
        facts: CICDFacts,
        *,
        policy: CICDPolicy | None = None,
        started: datetime | None = None,
    ) -> AnalyzerResult:
        started_at = started or datetime.now(UTC)
        effective_policy = policy or CICDPolicy(digest=facts.policy_digest)
        metrics, findings, limitations, score, diagnostics = _analysis(
            context,
            facts,
            effective_policy,
        )
        status: AnalyzerStatus
        if facts.status is CICDDataStatus.CI_NOT_CONFIGURED:
            status, score = AnalyzerStatus.SKIPPED, None
            limitations = _unique_limitations(
                [
                    *limitations,
                    Limitation(
                        reason="CI is explicitly not configured in SourceCraft.",
                        kind="missing_capability",
                        affected_scope="cicd",
                    ),
                ]
            )
        elif facts.status is CICDDataStatus.UNAVAILABLE:
            status, score = AnalyzerStatus.SKIPPED, None
            limitations = _unique_limitations(
                [
                    *limitations,
                    Limitation(
                        reason="SourceCraft CI inventory is unavailable.",
                        kind="missing_capability",
                        affected_scope="cicd",
                    ),
                ]
            )
        elif facts.status is CICDDataStatus.ERROR:
            status, score = AnalyzerStatus.ERROR, None
        elif facts.status in {
            CICDDataStatus.NO_RUNS,
            CICDDataStatus.INSUFFICIENT_HISTORY,
        }:
            status, score = AnalyzerStatus.INCONCLUSIVE, None
            limitations = _unique_limitations(
                [
                    *limitations,
                    Limitation(
                        reason="CI history is insufficient for a defensible score.",
                        kind="insufficient_denominator",
                        affected_scope="cicd",
                    ),
                ]
            )
        elif score is None:
            status = AnalyzerStatus.INCONCLUSIVE
            limitations = _unique_limitations(
                [
                    *limitations,
                    Limitation(
                        reason="Fewer than two score components have sufficient samples.",
                        kind="insufficient_denominator",
                        affected_scope="cicd",
                    ),
                ]
            )
        elif any(finding.severity == "critical" for finding in findings):
            status = AnalyzerStatus.FAIL
        elif findings or facts.status is CICDDataStatus.PARTIAL:
            status = AnalyzerStatus.WARN
        else:
            status = AnalyzerStatus.PASS

        evidence = _evidence(context, facts)
        source_versions = {
            "sourcecraft_cicd": facts.source_version,
            "sourcecraft_cicd_schema": facts.source_schema_version,
            "cicd_policy": effective_policy.policy_revision,
            "cicd_policy_digest": effective_policy.digest,
        }
        diagnostics = {
            **diagnostics,
            "cicd": facts.summary(),
            "cicd_status": facts.status.value,
            "cicd_policy_revision": effective_policy.policy_revision,
            "cicd_policy_digest": effective_policy.digest,
            "score": score,
        }
        duration_ms = max(0, int((datetime.now(UTC) - started_at).total_seconds() * 1000))
        log.info(
            "cicd_analysis_finished",
            repo_id=context.repo_id,
            facts_status=facts.status.value,
            final_status=status.value,
            terminal_runs=len(facts.terminal_runs),
            finding_count=len(findings),
            score=round(score, 3) if score is not None else None,
            coverage=round(facts.coverage, 4),
            confidence=round(facts.confidence, 4),
            duration_ms=duration_ms,
        )
        return AnalyzerResult(
            analyzer_id=CICD_ANALYZER_ID,
            analyzer_version=CICD_DEFINITION.version,
            status=status,
            score=score,
            score_dimension=CICD_DIMENSION if score is not None else None,
            metrics=metrics,
            findings=findings,
            evidence=(evidence,),
            limitations=limitations,
            duration_ms=duration_ms,
            source_versions=source_versions,
            available_weight=1.0 if score is not None else 0.0,
            total_weight=1.0 if score is not None else 0.0,
            raw_payload_ref=(
                f"sourcecraft-cicd://{hashlib.sha256(str(facts.summary()).encode()).hexdigest()}"
            ),
            diagnostics=diagnostics,
        )


def cicd_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return CICDAnalyzer().run(context)


def register_cicd_adapter(registry: Any) -> None:
    if CICD_DEFINITION.id not in registry.ids():
        registry.register(CICD_DEFINITION, cicd_adapter)


__all__ = [
    "CICD_ANALYZER_ID",
    "CICD_DEFINITION",
    "CICDAnalyzer",
    "cicd_adapter",
    "register_cicd_adapter",
]
