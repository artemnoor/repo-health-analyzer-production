"""Issues-category analysis over normalized SourceCraft issue facts."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from .contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    Limitation,
    MetricValue,
)
from .issues_facts import (
    ISSUES_ANALYZER_VERSION,
    ActorClass,
    IssueCollectionFacts,
    IssueEventType,
    IssueFact,
    IssueMetricStatus,
    IssuesPolicy,
    IssueState,
    load_issues_policy,
    normalize_issue_inventory,
)

log = structlog.get_logger("issues.analyzer")

ISSUES_ANALYZER_ID = "chaoss.issues_prs"
ISSUES_DIMENSION = "delivery"


@dataclass(frozen=True)
class IssueAnalysis:
    metrics: tuple[MetricValue, ...]
    findings: tuple[Finding, ...]
    evidence: tuple[EvidenceRef, ...]
    limitations: tuple[Limitation, ...]
    component_scores: dict[str, float]
    component_coverage: dict[str, float]
    component_samples: dict[str, int]
    eligible_components: tuple[str, ...]
    score: float | None
    issue_status: IssueMetricStatus
    diagnostics: dict[str, Any]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _unique_refs(refs: Iterable[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    by_json: dict[str, EvidenceRef] = {}
    for ref in refs:
        by_json.setdefault(ref.model_dump_json(), ref)
    return tuple(by_json.values())


def _unique_limitations(limitations: Iterable[Limitation]) -> tuple[Limitation, ...]:
    by_json: dict[str, Limitation] = {}
    for limitation in limitations:
        by_json.setdefault(limitation.model_dump_json(), limitation)
    return tuple(by_json.values())


def _base_is_usable(result: AnalyzerResult) -> bool:
    return result.status in {
        AnalyzerStatus.PASS,
        AnalyzerStatus.WARN,
        AnalyzerStatus.FAIL,
    } and (result.score is not None or bool(result.metrics))


def percentile(values: Iterable[float], quantile: float) -> float | None:
    """Return deterministic linear-interpolated percentile."""
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _hours(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (_as_utc(end) - _as_utc(start)).total_seconds() / 3600.0
    return value if math.isfinite(value) and value >= 0 else None


def _quality(value: float | None, target: float, breach: float) -> float | None:
    if value is None:
        return None
    if value <= target:
        return 1.0
    if value >= breach:
        return 0.0
    return max(0.0, min(1.0, (breach - value) / (breach - target)))


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
        dimension=ISSUES_DIMENSION,
        value=value,
        unit=unit,
        population=population,
        denominator=denominator,
        evidence_refs=(evidence,),
    )


def _summary_evidence(context: AnalyzerContext, facts: IssueCollectionFacts) -> EvidenceRef:
    return EvidenceRef(
        source=facts.source_kind,
        source_commit=facts.source_version,
        json_pointer="/issues/facts",
        collected_at=context.as_of_ts,
        confidence=facts.confidence,
        redaction="partial",
    )


def _issue_evidence(context: AnalyzerContext, facts: IssueCollectionFacts, issue: IssueFact) -> EvidenceRef:
    return EvidenceRef(
        source=facts.source_kind,
        source_commit=facts.source_version,
        path=issue.url,
        json_pointer=f"/issues/{issue.issue_id}",
        collected_at=context.as_of_ts,
        confidence=max(0.0, min(1.0, facts.confidence * max(issue.field_coverage.values(), default=0.0))),
        redaction="partial",
    )


def _state_at(issue: IssueFact, as_of: datetime) -> IssueState:
    # A source may provide a terminal ``closed_at`` field without a complete
    # state-transition stream.  Normalization adds a synthetic ``opened``
    # event for such rows, so looking at transition events first would make a
    # genuinely closed issue appear open.  Merge the field and explicit
    # transitions into one timestamped state timeline; explicit events win a
    # tie because they carry stronger lifecycle semantics.
    candidates: list[tuple[datetime, int, str, IssueState]] = []
    if issue.closed_at is not None and _as_utc(issue.closed_at) <= as_of:
        candidates.append((_as_utc(issue.closed_at), 0, "closed_at", IssueState.CLOSED))
    for event in issue.events:
        if (
            event.is_state_transition
            and event.occurred_at <= as_of
            and event.event_type in {IssueEventType.OPENED, IssueEventType.CLOSED, IssueEventType.REOPENED}
        ):
            state = IssueState.CLOSED if event.event_type is IssueEventType.CLOSED else IssueState.OPEN
            candidates.append((event.occurred_at, 1, event.event_id, state))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]
    return issue.state


def _response_time(issue: IssueFact, as_of: datetime, policy: IssuesPolicy) -> float | None:
    if issue.created_at is None:
        return None
    comments = sorted(
        (
            event
            for event in issue.events
            if event.event_type is IssueEventType.COMMENTED
            and issue.created_at < event.occurred_at <= as_of
            and event.actor_class is ActorClass.HUMAN
            and not (
                policy.exclude_issue_author_from_response
                and issue.author_key is not None
                and event.actor_key == issue.author_key
            )
        ),
        key=lambda event: (event.occurred_at, event.event_id),
    )
    return _hours(issue.created_at, comments[0].occurred_at) if comments else None


def _stale(issue: IssueFact, as_of: datetime, policy: IssuesPolicy) -> bool | None:
    if issue.created_at is None or _state_at(issue, as_of) is not IssueState.OPEN:
        return False if _state_at(issue, as_of) is IssueState.CLOSED else None
    age = _hours(issue.created_at, as_of)
    if age is None or age < policy.stale_threshold_days * 24:
        return False
    cutoff = as_of - timedelta(days=policy.stale_threshold_days)
    qualifying = [
        event
        for event in issue.events
        if cutoff <= event.occurred_at <= as_of
        and event.event_type.value in policy.stale_activity_event_types
        and event.actor_class is ActorClass.HUMAN
    ]
    return not qualifying


def _close_time(issue: IssueFact, as_of: datetime) -> float | None:
    if issue.created_at is None:
        return None
    close_candidates = [
        event.occurred_at
        for event in issue.events
        if event.event_type is IssueEventType.CLOSED and event.occurred_at <= as_of
    ]
    closed_at = issue.closed_at if issue.closed_at is not None and issue.closed_at <= as_of else None
    if close_candidates:
        closed_at = max(close_candidates) if closed_at is None else max(closed_at, max(close_candidates))
    return _hours(issue.created_at, closed_at)


def _reopened(issue: IssueFact, as_of: datetime) -> bool:
    return any(
        event.event_type is IssueEventType.REOPENED
        and event.is_state_transition
        and event.occurred_at <= as_of
        for event in issue.events
    )


def _trend(facts: IssueCollectionFacts, policy: IssuesPolicy) -> tuple[dict[str, Any], ...]:
    buckets: list[dict[str, Any]] = []
    start = facts.analysis_start
    for index in range(max(1, math.ceil(policy.analysis_window_days / policy.trend_bucket_days))):
        bucket_start = start + timedelta(days=index * policy.trend_bucket_days)
        bucket_end = min(facts.analysis_end, bucket_start + timedelta(days=policy.trend_bucket_days))
        if bucket_start >= facts.analysis_end:
            break
        created = closed = human_comments = bot_comments = unknown_comments = reopened = 0
        for issue in facts.issues:
            if issue.created_at is not None and bucket_start <= issue.created_at < bucket_end:
                created += 1
            if issue.closed_at is not None and bucket_start <= issue.closed_at < bucket_end:
                closed += 1
            for event in issue.events:
                if not bucket_start <= event.occurred_at < bucket_end:
                    continue
                if event.event_type is IssueEventType.COMMENTED:
                    if event.actor_class is ActorClass.HUMAN:
                        human_comments += 1
                    elif event.actor_class is ActorClass.BOT:
                        bot_comments += 1
                    else:
                        unknown_comments += 1
                elif event.event_type is IssueEventType.REOPENED and event.is_state_transition:
                    reopened += 1
        buckets.append(
            {
                "index": index,
                "start": bucket_start.isoformat(),
                "end": bucket_end.isoformat(),
                "created": created,
                "closed": closed,
                "net": created - closed,
                "human_comments": human_comments,
                "bot_comments": bot_comments,
                "unknown_comments": unknown_comments,
                "reopened": reopened,
            }
        )
    return tuple(buckets)


def _age_buckets(ages: Iterable[float], thresholds_days: tuple[int, ...]) -> dict[str, int]:
    """Return stable, non-overlapping open-backlog age buckets."""
    ordered = tuple(sorted({int(value) for value in thresholds_days if int(value) > 0}))
    counts: dict[str, int] = {}
    previous = 0
    age_values = tuple(float(age) for age in ages)
    for threshold in ordered:
        lower = previous * 24.0
        upper = threshold * 24.0
        counts[f"issues:open_age_bucket_{previous}_{threshold}_days"] = sum(lower <= age < upper for age in age_values)
        previous = threshold
    if ordered:
        counts[f"issues:open_age_bucket_gt_{ordered[-1]}_days"] = sum(age >= ordered[-1] * 24.0 for age in age_values)
    return counts


def _findings(
    context: AnalyzerContext,
    facts: IssueCollectionFacts,
    policy: IssuesPolicy,
    eligible: list[IssueFact],
    responses: dict[str, float | None],
    stale_values: dict[str, bool | None],
    close_values: dict[str, float | None],
) -> tuple[tuple[Finding, ...], tuple[EvidenceRef, ...]]:
    candidates: list[tuple[tuple[int, float, str], Finding, EvidenceRef]] = []
    for issue in eligible:
        evidence = _issue_evidence(context, facts, issue)
        age = _hours(issue.created_at, facts.as_of) or 0.0
        response = responses.get(issue.issue_id)
        close_time = close_values.get(issue.issue_id)
        stale = stale_values.get(issue.issue_id)
        if stale is True:
            finding = Finding(
                id=f"{ISSUES_ANALYZER_ID}:stale:{issue.issue_id}",
                analyzer_id=ISSUES_ANALYZER_ID,
                subject=f"issue:{issue.issue_id}",
                dimension=ISSUES_DIMENSION,
                severity="high",
                confidence=evidence.confidence,
                reason=f"Issue {issue.issue_id} is stale: open for {age / 24.0:.2f} days with no qualifying human activity in the stale window.",
                evidence_refs=(evidence,),
                remediation="Review, update, close, or explicitly re-scope the stale issue.",
            )
            candidates.append(((3, age, issue.issue_id), finding, evidence))
        if facts.comments_available is True and response is None:
            finding = Finding(
                id=f"{ISSUES_ANALYZER_ID}:unanswered:{issue.issue_id}",
                analyzer_id=ISSUES_ANALYZER_ID,
                subject=f"issue:{issue.issue_id}",
                dimension=ISSUES_DIMENSION,
                severity="medium",
                confidence=evidence.confidence,
                reason=f"Issue {issue.issue_id} has no qualifying human response in the analysis window.",
                evidence_refs=(evidence,),
                remediation="Provide a human response or document why the issue does not require one.",
            )
            candidates.append(((2, age, issue.issue_id), finding, evidence))
        elif facts.comments_available is True and response is not None and response > policy.response_median_breach_hours:
            finding = Finding(
                id=f"{ISSUES_ANALYZER_ID}:slow-response:{issue.issue_id}",
                analyzer_id=ISSUES_ANALYZER_ID,
                subject=f"issue:{issue.issue_id}",
                dimension=ISSUES_DIMENSION,
                severity="medium",
                confidence=evidence.confidence,
                reason=f"First qualifying human response took {response:.2f} hours.",
                evidence_refs=(evidence,),
                remediation="Reduce time to first human response for newly opened issues.",
            )
            candidates.append(((2, response, issue.issue_id), finding, evidence))
        if close_time is not None and close_time > policy.close_p75_breach_hours:
            finding = Finding(
                id=f"{ISSUES_ANALYZER_ID}:slow-close:{issue.issue_id}",
                analyzer_id=ISSUES_ANALYZER_ID,
                subject=f"issue:{issue.issue_id}",
                dimension=ISSUES_DIMENSION,
                severity="medium",
                confidence=evidence.confidence,
                reason=f"Issue close time was {close_time:.2f} hours.",
                evidence_refs=(evidence,),
                remediation="Review the resolution workflow for long-running issues.",
            )
            candidates.append(((2, close_time, issue.issue_id), finding, evidence))
    candidates.sort(key=lambda item: (-item[0][0], -item[0][1], item[0][2], item[1].id))
    selected = candidates[: policy.maximum_findings]
    return tuple(item[1] for item in selected), _unique_refs(item[2] for item in selected)


def _limitation(reason: str, kind: str, evidence: EvidenceRef | None = None) -> Limitation:
    refs = (evidence,) if evidence is not None else ()
    return Limitation(reason=reason, kind=kind, affected_scope="issues", evidence_refs=refs)


def analyze_issue_facts(
    context: AnalyzerContext,
    facts: IssueCollectionFacts,
    policy: IssuesPolicy,
) -> IssueAnalysis:
    """Calculate issue metrics and local category score without side effects."""
    summary_ref = _summary_evidence(context, facts)
    issue_status = facts.status
    issues = tuple(facts.issues)
    snapshot_issues = [issue for issue in issues if issue.is_pull_request is not True]
    eligible = [
        issue
        for issue in snapshot_issues
        if issue.created_at is not None
        and facts.analysis_start <= issue.created_at <= facts.analysis_end
    ]
    mature = [
        issue
        for issue in eligible
        if _hours(issue.created_at, facts.as_of) is not None
        and (_hours(issue.created_at, facts.as_of) or 0.0) >= policy.maturity_window_days * 24
    ]
    open_issues = [issue for issue in snapshot_issues if _state_at(issue, facts.as_of) is IssueState.OPEN]
    closed_issues = [issue for issue in snapshot_issues if _state_at(issue, facts.as_of) is IssueState.CLOSED]
    closed_mature = [issue for issue in mature if _state_at(issue, facts.as_of) is IssueState.CLOSED]
    response_values = {
        issue.issue_id: _response_time(issue, facts.as_of, policy) if facts.comments_available is True else None
        for issue in eligible
    }
    answered_values = [value for value in response_values.values() if value is not None]
    response_available = facts.comments_available is True
    unanswered = len(eligible) - len(answered_values) if response_available else None
    close_values = {issue.issue_id: _close_time(issue, facts.as_of) for issue in mature}
    close_durations = [value for value in close_values.values() if value is not None]
    stale_values = {
        issue.issue_id: _stale(issue, facts.as_of, policy) if facts.comments_available is True else None
        for issue in open_issues
    }
    stale_count = sum(value is True for value in stale_values.values())
    unknown_stale_count = sum(value is None for value in stale_values.values())
    open_ages = [value for value in (_hours(issue.created_at, facts.as_of) for issue in open_issues) if value is not None]
    reopen_measured = facts.state_events_available is True
    reopened_count = sum(_reopened(issue, facts.as_of) for issue in snapshot_issues) if reopen_measured else None
    comment_counts = Counter(
        event.actor_class.value
        for issue in snapshot_issues
        for event in issue.events
        if event.event_type is IssueEventType.COMMENTED
    )
    trends = _trend(facts, policy)
    closure_ratio = len(closed_mature) / len(mature) if mature else None
    unanswered_ratio = unanswered / len(eligible) if response_available and eligible else None
    stale_denominator = len(open_issues) - unknown_stale_count
    stale_ratio = stale_count / stale_denominator if stale_denominator > 0 else None
    reopen_ratio = reopened_count / len(snapshot_issues) if reopened_count is not None and snapshot_issues else None
    response_median = percentile(answered_values, 0.50)
    response_p75 = percentile(answered_values, 0.75)
    close_median = percentile(close_durations, 0.50)
    close_p75 = percentile(close_durations, 0.75)
    open_age_median = percentile(open_ages, 0.50)
    open_age_p75 = percentile(open_ages, 0.75)
    old_open_count = sum(age >= policy.old_backlog_threshold_days * 24.0 for age in open_ages)
    age_buckets = _age_buckets(open_ages, policy.age_buckets_days)

    metrics: list[MetricValue] = [
        _metric("issues:open_issues", len(open_issues), summary_ref, unit="issues", population=len(snapshot_issues), denominator=len(snapshot_issues)),
        _metric("issues:closed_issues", len(closed_issues), summary_ref, unit="issues", population=len(snapshot_issues), denominator=len(snapshot_issues)),
        _metric("issues:closure_ratio", closure_ratio, summary_ref, unit="ratio", population=len(closed_mature), denominator=len(mature)),
        _metric("issues:first_human_response_count", len(answered_values) if response_available else None, summary_ref, unit="issues", population=len(answered_values) if response_available else None, denominator=len(eligible) if response_available else None),
        _metric("issues:unanswered_issues", unanswered, summary_ref, unit="issues", population=unanswered, denominator=len(eligible) if response_available else None),
        _metric("issues:unanswered_ratio", unanswered_ratio, summary_ref, unit="ratio", population=unanswered, denominator=len(eligible) if response_available else None),
        _metric("issues:first_response_median_hours", response_median if response_available else None, summary_ref, unit="hours", population=len(answered_values) if response_available else None, denominator=len(eligible) if response_available else None),
        _metric("issues:first_response_p75_hours", response_p75 if response_available else None, summary_ref, unit="hours", population=len(answered_values) if response_available else None, denominator=len(eligible) if response_available else None),
        _metric("issues:time_to_close_median_hours", close_median, summary_ref, unit="hours", population=len(close_durations), denominator=len(mature)),
        _metric("issues:time_to_close_p75_hours", close_p75, summary_ref, unit="hours", population=len(close_durations), denominator=len(mature)),
        _metric("issues:stale_open_issues", stale_count, summary_ref, unit="issues", population=stale_count, denominator=stale_denominator),
        _metric("issues:stale_ratio", stale_ratio, summary_ref, unit="ratio", population=stale_count, denominator=stale_denominator),
        _metric("issues:open_age_median_hours", open_age_median, summary_ref, unit="hours", population=len(open_ages), denominator=len(open_issues)),
        _metric("issues:open_age_p75_hours", open_age_p75, summary_ref, unit="hours", population=len(open_ages), denominator=len(open_issues)),
        _metric("issues:oldest_open_age_hours", max(open_ages) if open_ages else None, summary_ref, unit="hours", population=len(open_ages), denominator=len(open_issues)),
        _metric("issues:old_open_issues", old_open_count, summary_ref, unit="issues", population=old_open_count, denominator=len(open_issues)),
        _metric("issues:old_open_ratio", old_open_count / len(open_issues) if open_issues else None, summary_ref, unit="ratio", population=old_open_count, denominator=len(open_issues)),
        _metric("issues:reopened_issues", reopened_count, summary_ref, unit="issues", population=reopened_count, denominator=len(snapshot_issues)),
        _metric("issues:reopen_ratio", reopen_ratio, summary_ref, unit="ratio", population=reopened_count, denominator=len(snapshot_issues)),
        _metric("issues:comments_human", comment_counts.get(ActorClass.HUMAN.value, 0), summary_ref, unit="comments", population=comment_counts.get(ActorClass.HUMAN.value, 0), denominator=sum(comment_counts.values())),
        _metric("issues:comments_bot", comment_counts.get(ActorClass.BOT.value, 0), summary_ref, unit="comments", population=comment_counts.get(ActorClass.BOT.value, 0), denominator=sum(comment_counts.values())),
        _metric("issues:comments_unknown", comment_counts.get(ActorClass.UNKNOWN.value, 0), summary_ref, unit="comments", population=comment_counts.get(ActorClass.UNKNOWN.value, 0), denominator=sum(comment_counts.values())),
        _metric("issues:sample_size", len(eligible), summary_ref, unit="issues", population=len(eligible), denominator=len(eligible)),
    ]
    for name, count in age_buckets.items():
        metrics.append(_metric(name, count, summary_ref, unit="issues", population=count, denominator=len(open_issues)))
    for bucket in trends:
        prefix = f"issues:trend:{bucket['index']}"
        for key, unit in (
            ("created", "issues"),
            ("closed", "issues"),
            ("net", "issues"),
            ("human_comments", "comments"),
            ("bot_comments", "comments"),
            ("unknown_comments", "comments"),
            ("reopened", "issues"),
        ):
            metrics.append(_metric(f"{prefix}:{key}", bucket[key], summary_ref, unit=unit, population=bucket[key], denominator=1))

    response_field_coverage = facts.confidence if facts.comments_available is True else 0.0
    if facts.comments_available is True and comment_counts:
        response_field_coverage *= facts.actor_metadata_coverage
    response_eligible = len(eligible) >= policy.minimum_sample and response_field_coverage >= policy.minimum_coverage
    mature_field_coverage = facts.confidence
    resolution_eligible = len(mature) >= policy.minimum_sample and mature_field_coverage >= policy.partial_component_min_coverage
    stale_coverage_available = not open_issues or not any(value is None for value in stale_values.values())
    age_coverage_available = len(open_ages) == len(open_issues)
    backlog_eligible = (
        len(snapshot_issues) >= policy.minimum_sample
        and facts.coverage >= policy.partial_component_min_coverage
        and age_coverage_available
        and stale_coverage_available
    )
    trend_total = sum(bucket["created"] + bucket["closed"] for bucket in trends)
    maintenance_eligible = trend_total >= policy.minimum_sample and facts.coverage >= policy.partial_component_min_coverage

    response_latency = 0.0 if not answered_values else (
        0.5 * (_quality(response_median, policy.response_median_target_hours, policy.response_median_breach_hours) or 0.0)
        + 0.5 * (_quality(response_p75, policy.response_p75_target_hours, policy.response_p75_breach_hours) or 0.0)
    )
    responsiveness_score = 100.0 * (len(answered_values) / len(eligible) if eligible else 0.0) * response_latency
    close_latency = 0.0 if not close_durations else (
        0.5 * (_quality(close_median, policy.close_median_target_hours, policy.close_median_breach_hours) or 0.0)
        + 0.5 * (_quality(close_p75, policy.close_p75_target_hours, policy.close_p75_breach_hours) or 0.0)
    )
    resolution_score = 100.0 * (closure_ratio or 0.0) * close_latency
    if reopened_count and reopen_ratio is not None:
        resolution_score *= max(0.0, 1.0 - 0.50 * reopen_ratio)
    if not open_issues and backlog_eligible:
        backlog_score = 50.0
    elif backlog_eligible:
        age_quality = _quality(open_age_p75, policy.backlog_age_target_hours, policy.backlog_age_breach_hours) or 0.0
        if stale_coverage_available:
            stale_quality = 1.0 - (stale_ratio or 0.0)
            backlog_score = 100.0 * (0.60 * stale_quality + 0.40 * age_quality)
        else:
            # Counts and age remain valid even when comments are unavailable.
            # The component stays measurable, while the diagnostics expose
            # that the stale sub-signal was excluded from its formula.
            backlog_score = 100.0 * age_quality
    else:
        backlog_score = 0.0
    maintenance_score = 100.0 * sum(bucket["closed"] for bucket in trends) / trend_total if trend_total else 0.0
    component_scores = {
        "responsiveness": max(0.0, min(100.0, responsiveness_score)),
        "resolution": max(0.0, min(100.0, resolution_score)),
        "backlog_health": max(0.0, min(100.0, backlog_score)),
        "maintenance_trend": max(0.0, min(100.0, maintenance_score)),
    }
    component_coverage = {
        "responsiveness": response_field_coverage,
        "resolution": mature_field_coverage,
        "backlog_health": facts.coverage,
        "maintenance_trend": facts.coverage,
    }
    component_samples = {
        "responsiveness": len(eligible),
        "resolution": len(mature),
        "backlog_health": len(snapshot_issues),
        "maintenance_trend": trend_total,
    }
    eligible_components = tuple(
        name
        for name, allowed in (
            ("responsiveness", response_eligible),
            ("resolution", resolution_eligible),
            ("backlog_health", backlog_eligible),
            ("maintenance_trend", maintenance_eligible),
        )
        if allowed
    )
    score: float | None = None
    if len(eligible_components) >= 2 and any(name in eligible_components for name in ("resolution", "backlog_health")):
        weights = {
            "responsiveness": policy.responsiveness_weight,
            "resolution": policy.resolution_weight,
            "backlog_health": policy.backlog_weight,
            "maintenance_trend": policy.maintenance_weight,
        }
        total_weight = sum(weights[name] for name in eligible_components)
        if total_weight > 0:
            score = sum(component_scores[name] * weights[name] for name in eligible_components) / total_weight

    findings, finding_evidence = _findings(context, facts, policy, eligible, response_values, stale_values, close_values)
    if issue_status in {IssueMetricStatus.UNAVAILABLE, IssueMetricStatus.ERROR}:
        # Preserve the source-state distinction at the public boundary.  A
        # missing/failed collector must not look like a long list of numeric
        # zeroes or null-valued issue observations.
        metrics = [_metric("issues:sample_size", None, summary_ref, unit="issues")]
        findings = ()
        finding_evidence = ()
        trends = ()
        component_scores = {}
        component_coverage = {}
        component_samples = {}
        eligible_components = ()
        score = None
    limitations: list[Limitation] = []
    for reason in facts.limitations:
        kind = "missing_capability" if "not supplied" in reason.lower() or "permission" in reason.lower() else "insufficient_denominator"
        limitations.append(_limitation(reason, kind, summary_ref))
    if facts.comments_available is not True:
        limitations.append(_limitation("Human response metrics are unavailable because comments are not complete", "missing_capability", summary_ref))
    if facts.state_events_available is not True:
        limitations.append(_limitation("Reopen metrics are not applicable without explicit state events", "unsupported", summary_ref))
    if len(eligible) < policy.minimum_sample:
        limitations.append(_limitation("Issue response sample is below the configured minimum", "insufficient_denominator", summary_ref))
    diagnostics = {
        "issue_population_status": issue_status.value,
        "source_summary": facts.summary(),
        "metric_statuses": {
            "counts": IssueMetricStatus.MEASURED.value if facts.status in {IssueMetricStatus.MEASURED, IssueMetricStatus.PARTIAL} else facts.status.value,
            "responsiveness": IssueMetricStatus.MEASURED.value if response_eligible else IssueMetricStatus.UNAVAILABLE.value,
            "resolution": IssueMetricStatus.MEASURED.value if resolution_eligible else IssueMetricStatus.UNAVAILABLE.value,
            "backlog": IssueMetricStatus.MEASURED.value if backlog_eligible else IssueMetricStatus.UNAVAILABLE.value,
            "reopened": IssueMetricStatus.MEASURED.value if facts.state_events_available is True else IssueMetricStatus.NOT_APPLICABLE.value,
        },
        "trend": trends,
        "open_age_buckets": age_buckets,
        "old_open_count": old_open_count,
        "component_scores": component_scores,
        "component_coverage": component_coverage,
        "component_samples": component_samples,
        "eligible_components": eligible_components,
        "component_availability": {
            "responsiveness": response_eligible,
            "resolution": resolution_eligible,
            "backlog_health": backlog_eligible,
            "maintenance_trend": maintenance_eligible,
        },
        "partial_component_min_coverage": policy.partial_component_min_coverage,
        "stale_status": IssueMetricStatus.MEASURED.value if stale_coverage_available else IssueMetricStatus.UNAVAILABLE.value,
        "score_coverage": (
            sum(
                {
                    "responsiveness": policy.responsiveness_weight,
                    "resolution": policy.resolution_weight,
                    "backlog_health": policy.backlog_weight,
                    "maintenance_trend": policy.maintenance_weight,
                }[name]
                for name in eligible_components
            )
            / sum(
                (
                    policy.responsiveness_weight,
                    policy.resolution_weight,
                    policy.backlog_weight,
                    policy.maintenance_weight,
                )
            )
            if eligible_components
            else 0.0
        ),
        "score": score,
        "score_denominator": sum(
            {
                "responsiveness": policy.responsiveness_weight,
                "resolution": policy.resolution_weight,
                "backlog_health": policy.backlog_weight,
                "maintenance_trend": policy.maintenance_weight,
            }[name]
            for name in eligible_components
        ),
        "double_count_guard": "one_aggregate_analyzer_score_delivery_no_scored_component_metrics",
    }
    return IssueAnalysis(
        metrics=tuple(metrics),
        findings=findings,
        evidence=_unique_refs((summary_ref, *finding_evidence)),
        limitations=_unique_limitations(limitations),
        component_scores=component_scores,
        component_coverage=component_coverage,
        component_samples=component_samples,
        eligible_components=eligible_components,
        score=score,
        issue_status=issue_status,
        diagnostics=diagnostics,
    )


class IssuesAnalyzer:
    """Compose normalized issue facts into the existing Issues/PR result."""

    def __init__(self, *, policy_loader: Any = load_issues_policy) -> None:
        self.policy_loader = policy_loader

    def analyze(self, context: AnalyzerContext, base_result: AnalyzerResult) -> AnalyzerResult:
        started = datetime.now(UTC)
        try:
            policy = self.policy_loader()
            facts = normalize_issue_inventory(context, policy)
        except (OSError, TypeError, ValueError, ImportError) as exc:
            log.error("issues_policy_or_normalization_failed", repo_id=context.repo_id, error_type=type(exc).__name__)
            limitations = list(base_result.limitations)
            limitations.append(_limitation("Issues policy or source normalization failed", "error"))
            usable = _base_is_usable(base_result)
            return base_result.model_copy(
                update={
                    "status": AnalyzerStatus.WARN if usable else AnalyzerStatus.ERROR,
                    "score": base_result.score if usable else None,
                    "score_dimension": base_result.score_dimension if usable else None,
                    "limitations": _unique_limitations(limitations),
                    "diagnostics": {
                        **base_result.diagnostics,
                        "issues": {"failure_kind": type(exc).__name__},
                        "issues_status": IssueMetricStatus.ERROR.value,
                    },
                }
            )

        analysis = analyze_issue_facts(context, facts, policy)
        metrics = tuple((*base_result.metrics, *analysis.metrics))
        evidence = _unique_refs((*base_result.evidence, *analysis.evidence))
        limitations = _unique_limitations((*base_result.limitations, *analysis.limitations))
        base_usable = _base_is_usable(base_result)
        final_score = base_result.score
        final_dimension = base_result.score_dimension
        applied_share = 0.0
        if analysis.score is not None:
            if base_result.score is not None:
                applied_share = policy.issues_max_share
                final_score = (base_result.score * (1.0 - applied_share)) + (analysis.score * applied_share)
            else:
                applied_share = 1.0
                final_score = analysis.score
            final_dimension = base_result.score_dimension or ISSUES_DIMENSION

        if facts.status is IssueMetricStatus.UNAVAILABLE:
            status = base_result.status if base_usable else AnalyzerStatus.SKIPPED
            if not base_usable:
                final_score = None
                final_dimension = None
        elif facts.status is IssueMetricStatus.ERROR:
            status = AnalyzerStatus.WARN if base_usable else AnalyzerStatus.ERROR
            if not base_usable:
                final_score = None
                final_dimension = None
        elif facts.status is IssueMetricStatus.NO_ISSUES:
            status = base_result.status if base_usable else AnalyzerStatus.INCONCLUSIVE
            if not base_usable:
                final_score = None
                final_dimension = None
        elif facts.status is IssueMetricStatus.PARTIAL:
            status = AnalyzerStatus.WARN if base_result.status is not AnalyzerStatus.FAIL else base_result.status
        else:
            status = AnalyzerStatus.WARN if analysis.findings or analysis.limitations else (base_result.status if base_result.status in {AnalyzerStatus.WARN, AnalyzerStatus.FAIL} else AnalyzerStatus.PASS)

        diagnostics = dict(base_result.diagnostics)
        diagnostics.update(
            {
                "issues": analysis.diagnostics,
                "issues_status": analysis.issue_status.value,
                "issues_policy_revision": policy.policy_revision,
                "issues_policy_digest": policy.digest,
                "issues_score": {
                    "quality_score": analysis.score,
                    "applied_share": applied_share,
                    "final_score": final_score,
                    "score_dimension": final_dimension,
                    "eligible_components": analysis.eligible_components,
                },
            }
        )
        source_versions = dict(base_result.source_versions)
        source_versions["issues_source"] = facts.source_version
        source_versions["issues_policy"] = policy.policy_revision
        source_versions["open_digger_methodology"] = "63e4b89ecd525221be95fe2a48a714ebb3c722ec"
        source_versions["chaoss_metrics_methodology"] = "fae1f4dfc533a6f28499bdba3fb1514ccabc2018"
        raw_ref = f"issues://{hashlib.sha256(json.dumps(analysis.diagnostics, sort_keys=True, default=str).encode()).hexdigest()}"
        elapsed_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        log.info(
            "issues_composition_finished",
            repo_id=context.repo_id,
            issue_status=analysis.issue_status.value,
            base_status=base_result.status.value,
            final_status=status.value,
            issue_count=len(facts.issues),
            finding_count=len(analysis.findings),
            eligible_components=analysis.eligible_components,
            issue_score=round(analysis.score, 3) if analysis.score is not None else None,
            applied_share=round(applied_share, 3),
            duration_ms=elapsed_ms,
        )
        return base_result.model_copy(
            update={
                "analyzer_version": policy.policy_revision,
                "status": status,
                "score": final_score,
                "score_dimension": final_dimension,
                "metrics": metrics,
                "findings": tuple((*base_result.findings, *analysis.findings)),
                "evidence": evidence,
                "limitations": limitations,
                "source_versions": source_versions,
                "available_weight": max(base_result.available_weight, 1.0 if final_score is not None else 0.0),
                "total_weight": max(base_result.total_weight, base_result.available_weight, 1.0 if final_score is not None else 0.0),
                "raw_payload_ref": raw_ref,
                "duration_ms": base_result.duration_ms + elapsed_ms,
                "diagnostics": diagnostics,
            }
        )


__all__ = [
    "ISSUES_ANALYZER_ID",
    "ISSUES_ANALYZER_VERSION",
    "ISSUES_DIMENSION",
    "IssueAnalysis",
    "IssuesAnalyzer",
    "analyze_issue_facts",
    "percentile",
]
