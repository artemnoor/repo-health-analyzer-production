"""Normalized SourceCraft CI/CD facts and repository-owned policy.

The health edge supplies the SourceCraft inventory. These immutable facts are
the only data visible to the CI/CD analyzer; no raw API response tree or
credential crosses this boundary.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import structlog
import yaml

from .process import workspace_root

log = structlog.get_logger("cicd.facts")

CICD_CONFIG_RELATIVE = Path("config/analyzers/cicd.yaml")
CICD_POLICY_REVISION = "cicd-sourcecraft-policy-v1"
CICD_SCHEMA_VERSION = "sourcecraft-cicd-inventory-v1"
CICD_SOURCE_COMMIT = "sourcecraft-cicd-api"
CICD_VALIDATED_VERSION = "sourcecraft-cicd-api-v1"


class CICDDataStatus(StrEnum):
    """Internal source status retained in AnalyzerResult diagnostics."""

    MEASURED = "MEASURED"
    CI_NOT_CONFIGURED = "CI_NOT_CONFIGURED"
    NO_RUNS = "NO_RUNS"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CICDRunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    UNKNOWN = "UNKNOWN"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _bounded(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Return the deterministic linear-interpolation percentile."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


@dataclass(frozen=True)
class CICDPolicy:
    """Validated, versioned CI/CD analyzer policy."""

    policy_revision: str = CICD_POLICY_REVISION
    source_commit: str = CICD_SOURCE_COMMIT
    schema_version: str = CICD_SCHEMA_VERSION
    analysis_window_days: int = 90
    current_period_days: int = 30
    previous_period_days: int = 30
    oldest_period_days: int = 30
    minimum_terminal_runs: int = 5
    minimum_decisive_runs: int = 5
    preferred_terminal_runs: int = 10
    minimum_duration_runs: int = 5
    minimum_trend_runs_per_period: int = 3
    minimum_duration_trend_runs_per_period: int = 5
    max_pages: int = 1000
    page_size: int = 100
    maximum_findings: int = 25
    failure_trend_scale: float = 0.20
    duration_trend_scale: float = 0.50
    failure_warning_rate: float = 0.20
    failure_critical_rate: float = 0.50
    warning_streak: int = 2
    critical_streak: int = 5
    p50_target_seconds: float = 300.0
    p50_breach_seconds: float = 1800.0
    p95_target_seconds: float = 900.0
    p95_breach_seconds: float = 3600.0
    reliability_weight: float = 0.75
    failure_streak_weight: float = 0.15
    duration_weight: float = 0.05
    trend_weight: float = 0.05
    digest: str = ""

    def __post_init__(self) -> None:
        positive = (
            "analysis_window_days",
            "current_period_days",
            "previous_period_days",
            "oldest_period_days",
            "minimum_terminal_runs",
            "minimum_decisive_runs",
            "preferred_terminal_runs",
            "minimum_duration_runs",
            "minimum_trend_runs_per_period",
            "minimum_duration_trend_runs_per_period",
            "max_pages",
            "page_size",
            "maximum_findings",
            "warning_streak",
            "critical_streak",
        )
        if any(int(getattr(self, name)) <= 0 for name in positive):
            raise ValueError("CI/CD policy integer values must be positive")
        if (
            self.current_period_days + self.previous_period_days + self.oldest_period_days
            > self.analysis_window_days
        ):
            raise ValueError("CI/CD comparison windows exceed the analysis horizon")
        if self.minimum_terminal_runs > self.preferred_terminal_runs:
            raise ValueError("minimum terminal runs exceed preferred sample")
        if self.minimum_decisive_runs > self.minimum_terminal_runs:
            raise ValueError("minimum decisive runs exceed minimum terminal runs")
        for name in (
            "failure_trend_scale",
            "duration_trend_scale",
            "failure_warning_rate",
            "failure_critical_rate",
            "p50_target_seconds",
            "p50_breach_seconds",
            "p95_target_seconds",
            "p95_breach_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.failure_warning_rate >= self.failure_critical_rate:
            raise ValueError("failure warning rate must be below critical rate")
        if self.p50_target_seconds >= self.p50_breach_seconds:
            raise ValueError("P50 target must be below P50 breach")
        if self.p95_target_seconds >= self.p95_breach_seconds:
            raise ValueError("P95 target must be below P95 breach")
        weights = (
            self.reliability_weight,
            self.failure_streak_weight,
            self.duration_weight,
            self.trend_weight,
        )
        if any(float(weight) < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("CI/CD score weights must be non-negative with a positive total")
        object.__setattr__(self, "digest", str(self.digest or ""))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.relative_to(workspace_root()).as_posix().encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping(raw.get(key))


def load_cicd_policy(root: Path | None = None) -> CICDPolicy:
    """Load and validate the checked-in CI/CD policy."""
    project_root = Path(root or workspace_root()).resolve()
    path = project_root / CICD_CONFIG_RELATIVE
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    document = _mapping(raw)
    analyzer = _section(document, "analyzer")
    policy = _section(document, "policy")
    windows = _section(policy, "windows")
    thresholds = _section(policy, "thresholds")
    score = _section(policy, "score")
    pagination = _section(policy, "pagination")
    revision = str(policy.get("policy_revision") or analyzer.get("version") or CICD_POLICY_REVISION)
    result = CICDPolicy(
        policy_revision=revision,
        source_commit=str(analyzer.get("source_commit") or CICD_SOURCE_COMMIT),
        schema_version=str(analyzer.get("schema_version") or CICD_SCHEMA_VERSION),
        analysis_window_days=int(windows.get("analysis_window_days", 90)),
        current_period_days=int(windows.get("current_period_days", 30)),
        previous_period_days=int(windows.get("previous_period_days", 30)),
        oldest_period_days=int(windows.get("oldest_period_days", 30)),
        minimum_terminal_runs=int(thresholds.get("minimum_terminal_runs", 5)),
        minimum_decisive_runs=int(thresholds.get("minimum_decisive_runs", 5)),
        preferred_terminal_runs=int(thresholds.get("preferred_terminal_runs", 10)),
        minimum_duration_runs=int(thresholds.get("minimum_duration_runs", 5)),
        minimum_trend_runs_per_period=int(thresholds.get("minimum_trend_runs_per_period", 3)),
        minimum_duration_trend_runs_per_period=int(
            thresholds.get("minimum_duration_trend_runs_per_period", 5)
        ),
        max_pages=int(pagination.get("max_pages", 1000)),
        page_size=int(pagination.get("page_size", 100)),
        maximum_findings=int(thresholds.get("maximum_findings", 25)),
        failure_trend_scale=float(thresholds.get("failure_trend_scale", 0.20)),
        duration_trend_scale=float(thresholds.get("duration_trend_scale", 0.50)),
        failure_warning_rate=float(thresholds.get("failure_warning_rate", 0.20)),
        failure_critical_rate=float(thresholds.get("failure_critical_rate", 0.50)),
        warning_streak=int(thresholds.get("warning_streak", 2)),
        critical_streak=int(thresholds.get("critical_streak", 5)),
        p50_target_seconds=float(thresholds.get("p50_target_seconds", 300)),
        p50_breach_seconds=float(thresholds.get("p50_breach_seconds", 1800)),
        p95_target_seconds=float(thresholds.get("p95_target_seconds", 900)),
        p95_breach_seconds=float(thresholds.get("p95_breach_seconds", 3600)),
        reliability_weight=float(score.get("reliability_weight", 0.75)),
        failure_streak_weight=float(score.get("failure_streak_weight", 0.15)),
        duration_weight=float(score.get("duration_weight", 0.05)),
        trend_weight=float(score.get("trend_weight", 0.05)),
        digest=_digest(path),
    )
    if result.schema_version != CICD_SCHEMA_VERSION:
        raise ValueError(f"unsupported CI/CD schema version: {result.schema_version}")
    log.info(
        "cicd_policy_loaded",
        policy_revision=result.policy_revision,
        policy_digest=result.digest[:12],
        schema_version=result.schema_version,
        analysis_window_days=result.analysis_window_days,
    )
    return result


@dataclass(frozen=True)
class CICDRunFact:
    run_id: str
    run_slug: str | None = None
    workflow_id: str | None = None
    workflow_name: str | None = None
    task_ids: tuple[str, ...] = ()
    raw_status: str = ""
    status: CICDRunStatus = CICDRunStatus.UNKNOWN
    failure_kind: str | None = None
    event_type: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    duration_seconds: float | None = None
    derived_duration: bool = False
    commit_sha: str | None = None
    branch: str | None = None
    tag: str | None = None
    environment: str | None = None
    deployment_marker: str | None = None
    retry_group_id: str | None = None
    parent_run_id: str | None = None
    attempt: int | None = None
    correlation_id: str | None = None
    deep_link: str | None = None
    source_json_pointer: str | None = None
    source_page: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", str(self.run_id))
        for name in ("created_at", "started_at", "finished_at", "updated_at"):
            object.__setattr__(self, name, _utc(getattr(self, name)))
        if self.duration_seconds is not None:
            duration = float(self.duration_seconds)
            if not math.isfinite(duration) or duration < 0:
                raise ValueError("duration_seconds must be finite and non-negative")
            object.__setattr__(self, "duration_seconds", duration)
        if self.attempt is not None:
            object.__setattr__(self, "attempt", max(0, int(self.attempt)))
        object.__setattr__(self, "task_ids", tuple(sorted({str(item) for item in self.task_ids})))

    @property
    def terminal(self) -> bool:
        return self.status in {
            CICDRunStatus.SUCCESS,
            CICDRunStatus.FAILURE,
            CICDRunStatus.CANCELLED,
            CICDRunStatus.SKIPPED,
            CICDRunStatus.REJECTED,
        }

    @property
    def decisive(self) -> bool:
        return self.status in {CICDRunStatus.SUCCESS, CICDRunStatus.FAILURE}

    @property
    def terminal_at(self) -> datetime | None:
        return self.finished_at if self.terminal else None

    @property
    def workflow_key(self) -> str:
        return str(self.workflow_id or self.workflow_name or "")


def _run_reference(run: CICDRunFact | None) -> dict[str, Any] | None:
    if run is None:
        return None
    timestamp = run.updated_at or run.finished_at or run.created_at
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "workflow_id": run.workflow_id,
        "workflow_name": run.workflow_name,
        "duration_seconds": run.duration_seconds,
        "deep_link": run.deep_link,
    }


@dataclass(frozen=True)
class CICDRetryRelation:
    failed_run_id: str
    successful_run_id: str
    relation_key: str
    workflow_key: str | None = None
    commit_sha: str | None = None


@dataclass(frozen=True)
class CICDWindowFacts:
    name: str
    start: datetime
    end: datetime
    total_runs: int = 0
    terminal_runs: int = 0
    decisive_runs: int = 0
    counts: Mapping[str, int] = field(default_factory=dict)
    durations: tuple[float, ...] = ()
    p50_seconds: float | None = None
    p95_seconds: float | None = None
    success_rate: float | None = None
    failure_rate: float | None = None
    non_decisive_rate: float | None = None
    completion_health: float | None = None
    failure_streak: int = 0
    eligible_for_trend: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _utc(self.start) or self.start)
        object.__setattr__(self, "end", _utc(self.end) or self.end)
        object.__setattr__(
            self,
            "counts",
            MappingProxyType({str(k): int(v) for k, v in self.counts.items()}),
        )
        object.__setattr__(self, "durations", tuple(float(value) for value in self.durations))


@dataclass(frozen=True)
class CICDFacts:
    """Complete normalized input to the pure CI/CD analyzer."""

    status: CICDDataStatus
    as_of_at: datetime
    analysis_start: datetime
    analysis_end: datetime
    configured: bool | None = None
    configuration_source: str = "unknown"
    source_kind: str = "sourcecraft"
    source_key: str | None = None
    source_version: str = "unknown"
    source_schema_version: str = CICD_SCHEMA_VERSION
    source_snapshot_digest: str | None = None
    collector_identity: str | None = None
    permission_state: str = "unknown"
    runs: tuple[CICDRunFact, ...] = ()
    windows: tuple[CICDWindowFacts, ...] = ()
    latest_observed: CICDRunFact | None = None
    latest_terminal: CICDRunFact | None = None
    latest_successful: CICDRunFact | None = None
    consecutive_failure_streak: int = 0
    duplicate_record_count: int = 0
    malformed_record_count: int = 0
    unknown_status_count: int = 0
    out_of_window_count: int = 0
    pagination_complete: bool | None = None
    pages_fetched: int = 0
    records_observed: int = 0
    records_expected: int | None = None
    local_date_filter_applied: bool | None = None
    field_coverage: Mapping[str, float] = field(default_factory=dict)
    coverage: float = 0.0
    confidence: float = 0.0
    retry_detection_status: str = "UNAVAILABLE"
    retry_relations: tuple[CICDRetryRelation, ...] = ()
    dora_capabilities: Mapping[str, str] = field(default_factory=dict)
    metric_statuses: Mapping[str, str] = field(default_factory=dict)
    policy_digest: str = ""
    policy_revision: str = CICD_POLICY_REVISION
    limitations: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of_at", _utc(self.as_of_at) or self.as_of_at)
        object.__setattr__(self, "analysis_start", _utc(self.analysis_start) or self.analysis_start)
        object.__setattr__(self, "analysis_end", _utc(self.analysis_end) or self.analysis_end)
        object.__setattr__(self, "runs", tuple(sorted(self.runs, key=lambda item: item.run_id)))
        object.__setattr__(
            self,
            "retry_relations",
            tuple(
                sorted(
                    self.retry_relations,
                    key=lambda item: (item.failed_run_id, item.successful_run_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "field_coverage",
            MappingProxyType({str(k): _bounded(v) for k, v in self.field_coverage.items()}),
        )
        object.__setattr__(
            self,
            "dora_capabilities",
            MappingProxyType({str(k): str(v) for k, v in self.dora_capabilities.items()}),
        )
        object.__setattr__(
            self,
            "metric_statuses",
            MappingProxyType({str(k): str(v) for k, v in self.metric_statuses.items()}),
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
        object.__setattr__(self, "coverage", _bounded(self.coverage))
        object.__setattr__(self, "confidence", _bounded(self.confidence))

    @property
    def terminal_runs(self) -> tuple[CICDRunFact, ...]:
        return tuple(run for run in self.runs if run.terminal and run.finished_at is not None)

    @property
    def decisive_runs(self) -> tuple[CICDRunFact, ...]:
        return tuple(run for run in self.runs if run.decisive and run.finished_at is not None)

    @property
    def sample_size(self) -> int:
        return len(self.terminal_runs)

    def summary(self) -> dict[str, Any]:
        raw_record_count = self.diagnostics.get("raw_row_count")
        if not isinstance(raw_record_count, int):
            raw_record_count = self.records_observed
        deduplicated_record_count = self.diagnostics.get("deduplicated_row_count")
        if not isinstance(deduplicated_record_count, int):
            deduplicated_record_count = len(self.runs)
        return {
            "status": self.status.value,
            "configured": self.configured,
            "configuration_source": self.configuration_source,
            "source_kind": self.source_kind,
            "source_key": self.source_key,
            "source_version": self.source_version,
            "source_schema_version": self.source_schema_version,
            "source_snapshot_digest": self.source_snapshot_digest,
            "permission_state": self.permission_state,
            "total_runs": len(self.runs),
            "terminal_runs": len(self.terminal_runs),
            "decisive_runs": len(self.decisive_runs),
            "latest_run": _run_reference(self.latest_observed),
            "latest_terminal": _run_reference(self.latest_terminal),
            "latest_successful": _run_reference(self.latest_successful),
            "consecutive_failure_streak": self.consecutive_failure_streak,
            "pages_fetched": self.pages_fetched,
            "records_observed": self.records_observed,
            "records_expected": self.records_expected,
            "raw_record_count": raw_record_count,
            "deduplicated_record_count": deduplicated_record_count,
            "pagination_complete": self.pagination_complete,
            "local_date_filter_applied": self.local_date_filter_applied,
            "duplicate_record_count": self.duplicate_record_count,
            "malformed_record_count": self.malformed_record_count,
            "unknown_status_count": self.unknown_status_count,
            "out_of_window_count": self.out_of_window_count,
            "retry_detection_status": self.retry_detection_status,
            "retry_relation_count": len(self.retry_relations),
            "coverage": self.coverage,
            "confidence": self.confidence,
            "policy_revision": self.policy_revision,
            "policy_digest": self.policy_digest,
            "limitations": self.limitations,
        }


def window_bounds(
    as_of: datetime, policy: CICDPolicy
) -> tuple[tuple[str, datetime, datetime], ...]:
    """Return the half-open oldest, previous, and current comparison windows."""
    end = _utc(as_of) or as_of.replace(tzinfo=UTC)
    current_start = end - timedelta(days=policy.current_period_days)
    previous_start = current_start - timedelta(days=policy.previous_period_days)
    oldest_start = previous_start - timedelta(days=policy.oldest_period_days)
    return (
        ("oldest", oldest_start, previous_start),
        ("previous", previous_start, current_start),
        ("current", current_start, end),
    )


__all__ = [
    "CICD_CONFIG_RELATIVE",
    "CICD_POLICY_REVISION",
    "CICD_SCHEMA_VERSION",
    "CICD_SOURCE_COMMIT",
    "CICD_VALIDATED_VERSION",
    "CICDDataStatus",
    "CICDFacts",
    "CICDPolicy",
    "CICDRetryRelation",
    "CICDRunFact",
    "CICDRunStatus",
    "CICDWindowFacts",
    "load_cicd_policy",
    "percentile",
    "window_bounds",
]
