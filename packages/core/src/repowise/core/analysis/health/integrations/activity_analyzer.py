"""Composition boundary for the existing Activity analyzer.

The health edge owns the Activity result.  This helper adds the optional
PyDriller source to that result without exposing PyDriller objects to the
registry, orchestrator, or score engine.  SourceCraft/CollectOSS remains the
owner of platform activity such as pull requests, issues, and releases.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog

from ..calibration_policy_v2 import ACTIVITY_POLICY_REVISION, activity_score
from .contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Limitation,
    MetricValue,
)
from .pydriller_adapter import (
    PYDRILLER_POLICY_REVISION,
    GitActivityBaseline,
    PyDrillerAdapter,
    PyDrillerExecutionStatus,
    PyDrillerFacts,
    PyDrillerPolicy,
    load_pydriller_policy,
)

log = structlog.get_logger("activity.analyzer")

ACTIVITY_POLICY_VERSION = PYDRILLER_POLICY_REVISION
_HISTORY_DIMENSION = "history"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _bounded(value: object, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _unique_refs(refs: tuple[EvidenceRef, ...] | list[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    by_json: dict[str, EvidenceRef] = {}
    for ref in refs:
        by_json.setdefault(ref.model_dump_json(), ref)
    return tuple(by_json.values())


def _base_is_usable(result: AnalyzerResult) -> bool:
    return result.status in {
        AnalyzerStatus.PASS,
        AnalyzerStatus.WARN,
        AnalyzerStatus.FAIL,
    } and (result.score is not None or bool(result.metrics))


def _baseline_from_inventory(context: AnalyzerContext) -> GitActivityBaseline | None:
    supplied = context.inventory.get("git_activity_baseline")
    if isinstance(supplied, GitActivityBaseline):
        return supplied
    if isinstance(supplied, Mapping):
        source = str(supplied.get("source") or "sourcecraft.git")
        raw_hashes = supplied.get("commit_hashes")
        if isinstance(raw_hashes, str):
            raw_hashes = (raw_hashes,)
        commit_hashes = None
        if raw_hashes is not None:
            commit_hashes = frozenset(
                str(item).strip() for item in raw_hashes if str(item).strip()
            )
        return GitActivityBaseline(
            source=source,
            commit_hashes=commit_hashes,
            unique_commit_count=(
                int(supplied["unique_commit_count"])
                if supplied.get("unique_commit_count") is not None
                else None
            ),
            churn=int(supplied["churn"]) if supplied.get("churn") is not None else None,
            latest_activity_at=supplied.get("latest_activity_at")
            if isinstance(supplied.get("latest_activity_at"), datetime)
            else None,
        )
    raw_hashes = context.inventory.get("git_commit_hashes")
    if raw_hashes is None:
        return None
    if isinstance(raw_hashes, str):
        raw_hashes = (raw_hashes,)
    return GitActivityBaseline(
        source=str(context.inventory.get("git_source") or "sourcecraft.git"),
        commit_hashes=frozenset(str(item).strip() for item in raw_hashes if str(item).strip()),
    )


def _evidence(context: AnalyzerContext, facts: PyDrillerFacts) -> EvidenceRef:
    return EvidenceRef(
        source="pydriller",
        source_commit=facts.source_commit,
        tool_version=facts.tool_version,
        json_pointer="/pydriller/facts",
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
        dimension=_HISTORY_DIMENSION,
        value=value,
        unit=unit,
        population=population,
        denominator=denominator,
        evidence_refs=(evidence,),
    )


def _observed_metrics(
    context: AnalyzerContext,
    facts: PyDrillerFacts,
    evidence: EvidenceRef,
) -> tuple[MetricValue, ...]:
    if facts.execution_status not in {
        PyDrillerExecutionStatus.MEASURED,
        PyDrillerExecutionStatus.NO_ACTIVITY,
    }:
        return ()
    metrics: list[MetricValue] = [
        _metric(
            "pydriller:unique_commits",
            facts.unique_commit_count,
            evidence,
            unit="commits",
            population=facts.unique_commit_count,
            denominator=1 if facts.unique_commit_count else 0,
        ),
        _metric(
            "pydriller:commit_occurrences",
            facts.commit_occurrence_count,
            evidence,
            unit="occurrences",
            population=facts.commit_occurrence_count,
            denominator=1 if facts.commit_occurrence_count else 0,
        ),
        _metric(
            "pydriller:duplicate_commits",
            facts.duplicate_commit_count,
            evidence,
            unit="commits",
            population=facts.commit_occurrence_count,
            denominator=1 if facts.commit_occurrence_count else 0,
        ),
        _metric(
            "pydriller:unique_authors",
            facts.unique_author_count,
            evidence,
            unit="authors",
            population=facts.unique_author_count,
            denominator=1 if facts.unique_author_count else 0,
        ),
        _metric(
            "pydriller:unique_committers",
            facts.unique_committer_count,
            evidence,
            unit="committers",
            population=facts.unique_committer_count,
            denominator=1 if facts.unique_committer_count else 0,
        ),
        _metric("pydriller:additions", facts.total_additions, evidence, unit="lines"),
        _metric("pydriller:deletions", facts.total_deletions, evidence, unit="lines"),
        _metric("pydriller:churn", facts.total_churn, evidence, unit="lines"),
        _metric("pydriller:merge_commits", facts.merge_commit_count, evidence, unit="commits"),
        _metric("pydriller:empty_commits", facts.empty_commit_count, evidence, unit="commits"),
        _metric(
            "pydriller:low_change_commits",
            facts.low_change_commit_count,
            evidence,
            unit="commits",
        ),
        _metric(
            "pydriller:modified_file_records",
            facts.modified_file_record_count,
            evidence,
            unit="file_changes",
        ),
        _metric(
            "pydriller:tracked_unique_files",
            facts.tracked_unique_file_count,
            evidence,
            unit="files",
        ),
        _metric(
            "pydriller:active_periods",
            facts.active_period_count,
            evidence,
            unit="buckets",
            population=facts.observed_period_count,
            denominator=facts.observed_period_count,
        ),
        _metric(
            "pydriller:meaningful_activity_ratio",
            facts.meaningful_activity_ratio,
            evidence,
            unit="ratio",
            population=facts.unique_commit_count,
            denominator=facts.unique_commit_count,
        ),
        _metric(
            "pydriller:file_history_coverage",
            (
                facts.tracked_unique_file_count / facts.modified_file_record_count
                if facts.modified_file_record_count
                else None
            ),
            evidence,
            unit="ratio",
            population=facts.modified_file_record_count,
            denominator=facts.modified_file_record_count,
        ),
        _metric(
            "pydriller:coverage",
            facts.coverage,
            evidence,
            unit="ratio",
            population=1,
            denominator=1,
        ),
        _metric(
            "pydriller:confidence",
            facts.confidence,
            evidence,
            unit="ratio",
            population=1,
            denominator=1,
        ),
    ]
    for window in facts.windows:
        metrics.extend(
            (
                _metric(
                    f"pydriller:commits_{window.days}d",
                    window.commit_count,
                    evidence,
                    unit="commits",
                    population=window.commit_count,
                    denominator=1 if window.commit_count else 0,
                ),
                _metric(
                    f"pydriller:churn_{window.days}d",
                    window.churn,
                    evidence,
                    unit="lines",
                    population=window.commit_count,
                    denominator=1 if window.commit_count else 0,
                ),
                _metric(
                    f"pydriller:authors_{window.days}d",
                    window.author_count,
                    evidence,
                    unit="authors",
                    population=window.commit_count,
                    denominator=1 if window.commit_count else 0,
                ),
            )
        )
    for name, value, unit in (
        ("pydriller:latest_activity_age_days", facts.latest_activity_age_days, "days"),
        ("pydriller:current_inactivity_days", facts.current_inactivity_days, "days"),
        ("pydriller:longest_inactivity_days", facts.longest_inactivity_days, "days"),
    ):
        if value is not None:
            metrics.append(_metric(name, value, evidence, unit=unit, population=1, denominator=1))
    return tuple(metrics)


def _quality_score(facts: PyDrillerFacts, policy: PyDrillerPolicy) -> tuple[float, dict[str, float]] | None:
    if facts.execution_status is not PyDrillerExecutionStatus.MEASURED or not facts.has_activity:
        return None
    window_90d = next((window for window in facts.windows if window.days == 90), None)
    quality, components = activity_score(
        unique_commits=facts.unique_commit_count,
        latest_age_days=facts.latest_activity_age_days,
        meaningful_ratio=facts.meaningful_activity_ratio,
        commits_90d=window_90d.commit_count if window_90d else 0.0,
        authors_90d=window_90d.author_count if window_90d else 0.0,
        empty_commits=float(facts.empty_commit_count),
    )
    return quality, {
        **components,
        "calibration_policy": ACTIVITY_POLICY_REVISION,
    }


class ActivityAnalyzer:
    """Compose PyDriller history facts into the existing Activity result."""

    def __init__(
        self,
        *,
        pydriller_adapter: PyDrillerAdapter | None = None,
        policy_loader: Any = load_pydriller_policy,
    ) -> None:
        self.pydriller_adapter = pydriller_adapter or PyDrillerAdapter(policy_loader=policy_loader)
        self.policy_loader = policy_loader

    def analyze(
        self,
        context: AnalyzerContext,
        base_result: AnalyzerResult,
        *,
        baseline: GitActivityBaseline | None = None,
    ) -> AnalyzerResult:
        started = datetime.now(UTC)
        selected_baseline = baseline or _baseline_from_inventory(context)
        policy: PyDrillerPolicy | None = None
        try:
            policy = self.policy_loader()
        except (OSError, TypeError, ValueError):
            # The adapter owns the policy error state; do not duplicate its
            # error text or turn a policy failure into a synthetic zero score.
            policy = None
        facts = self.pydriller_adapter.collect(
            context,
            policy=policy,
            baseline=selected_baseline,
        )
        effective_policy = policy or PyDrillerPolicy()
        evidence = _evidence(context, facts)
        metrics = list(base_result.metrics)
        metrics.extend(_observed_metrics(context, facts, evidence))
        limitations = list(base_result.limitations)
        if facts.history_is_shallow:
            limitations.append(
                Limitation(
                    reason="PyDriller traversed a shallow Git history; activity is a lower bound",
                    kind="insufficient_denominator",
                    affected_scope="pydriller",
                    evidence_refs=(evidence,),
                )
            )
        if facts.truncated or facts.file_history_truncated:
            limitations.append(
                Limitation(
                    reason="PyDriller aggregation reached a configured safety bound",
                    kind="insufficient_denominator",
                    affected_scope="pydriller",
                    evidence_refs=(evidence,),
                )
            )
        quality_result = _quality_score(facts, effective_policy)
        quality_score = quality_result[0] if quality_result else None
        quality_inputs = quality_result[1] if quality_result else {}
        final_score = base_result.score
        final_dimension = base_result.score_dimension
        applied_share = 0.0
        if quality_score is not None:
            quality_metric_score = quality_score
            if base_result.score is not None:
                applied_share = effective_policy.pydriller_max_share
                final_score = (base_result.score * (1.0 - applied_share)) + (quality_score * applied_share)
                final_dimension = base_result.score_dimension or _HISTORY_DIMENSION
            else:
                applied_share = 1.0
                final_score = quality_score
                final_dimension = _HISTORY_DIMENSION
            metrics.append(
                MetricValue(
                    name="pydriller:activity_quality",
                    dimension=_HISTORY_DIMENSION,
                    value=quality_score,
                    unit="score",
                    # With an existing aggregate Activity score, keep the
                    # capped result score as the source contribution. A
                    # second scored metric would make the unchanged composite
                    # engine average the raw PyDriller score and bypass the
                    # configured share cap.
                    score=quality_metric_score if base_result.score is None else None,
                    population=facts.unique_commit_count,
                    denominator=1,
                    evidence_refs=(evidence,),
                )
            )

        usable_base = _base_is_usable(base_result)
        if facts.execution_status is PyDrillerExecutionStatus.MEASURED:
            if facts.history_is_shallow or facts.truncated or facts.file_history_truncated:
                status = AnalyzerStatus.WARN
            elif base_result.status in {AnalyzerStatus.WARN, AnalyzerStatus.FAIL}:
                status = base_result.status
            else:
                status = AnalyzerStatus.PASS
        elif facts.execution_status is PyDrillerExecutionStatus.NO_ACTIVITY:
            limitations.append(
                Limitation(
                    reason="PyDriller found no commits in the selected history scope",
                    kind="insufficient_denominator",
                    affected_scope="pydriller",
                    evidence_refs=(evidence,),
                )
            )
            status = base_result.status if usable_base else AnalyzerStatus.INCONCLUSIVE
            if not usable_base:
                final_score = None
                final_dimension = None
        elif facts.execution_status is PyDrillerExecutionStatus.UNAVAILABLE:
            limitations.append(
                Limitation(
                    reason=f"PyDriller source unavailable: {facts.failure_kind.value if facts.failure_kind else 'unknown'}",
                    kind="missing_capability",
                    affected_scope="pydriller",
                    evidence_refs=(evidence,),
                )
            )
            status = base_result.status if usable_base else AnalyzerStatus.SKIPPED
            if not usable_base:
                final_score = None
                final_dimension = None
        else:
            limitations.append(
                Limitation(
                    reason=f"PyDriller source failed: {facts.failure_kind.value if facts.failure_kind else 'error'}",
                    kind="timeout" if facts.failure_kind and facts.failure_kind.value == "timeout" else "error",
                    affected_scope="pydriller",
                    evidence_refs=(evidence,),
                )
            )
            status = AnalyzerStatus.WARN if usable_base and base_result.status is AnalyzerStatus.PASS else (
                base_result.status if usable_base else AnalyzerStatus.ERROR
            )
            if not usable_base:
                final_score = None
                final_dimension = None

        diagnostics = dict(base_result.diagnostics)
        diagnostics.update(
            {
                "pydriller": facts.summary(),
                "pydriller_status": facts.execution_status.value,
                "pydriller_failure_kind": facts.failure_kind.value if facts.failure_kind else None,
                "pydriller_coverage": facts.coverage,
                "pydriller_confidence": facts.confidence,
                "pydriller_overlap_status": facts.overlap_status,
                "pydriller_overlap_commit_count": facts.overlap_commit_count,
                "pydriller_new_commit_count": facts.new_commit_count,
                "double_count_guard": facts.double_count_guard,
                "pydriller_score": {
                    "quality_score": quality_score,
                    "applied_share": applied_share,
                    "denominator": 1 if quality_score is not None else 0,
                    **quality_inputs,
                },
            }
        )
        source_versions = dict(base_result.source_versions)
        source_versions["pydriller"] = facts.tool_version
        source_versions["pydriller_policy"] = facts.policy_revision
        elapsed_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        log.info(
            "activity_composition_finished",
            repo_id=context.repo_id,
            base_status=base_result.status.value,
            pydriller_status=facts.execution_status.value,
            overlap_status=facts.overlap_status,
            score_source_count=int(base_result.score is not None) + int(quality_score is not None),
            pydriller_score=round(quality_score, 3) if quality_score is not None else None,
            applied_share=round(applied_share, 3),
            final_status=status.value,
            duration_ms=elapsed_ms,
        )
        return base_result.model_copy(
            update={
                "analyzer_version": ACTIVITY_POLICY_VERSION,
                "status": status,
                "score": final_score,
                "score_dimension": final_dimension,
                "metrics": tuple(metrics),
                "evidence": _unique_refs((*base_result.evidence, evidence)),
                "limitations": tuple(_unique_limitations(limitations)),
                "source_versions": source_versions,
                "available_weight": max(base_result.available_weight, 1.0 if quality_score is not None else 0.0),
                "total_weight": max(
                    base_result.total_weight,
                    base_result.available_weight,
                    1.0 if quality_score is not None else 0.0,
                ),
                "duration_ms": base_result.duration_ms + elapsed_ms,
                "diagnostics": diagnostics,
            }
        )


def _unique_limitations(limitations: list[Limitation]) -> tuple[Limitation, ...]:
    by_json: dict[str, Limitation] = {}
    for limitation in limitations:
        by_json.setdefault(limitation.model_dump_json(), limitation)
    return tuple(by_json.values())


__all__ = ["ACTIVITY_POLICY_VERSION", "ActivityAnalyzer"]
