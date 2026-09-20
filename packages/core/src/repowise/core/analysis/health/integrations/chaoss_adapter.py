"""Adapters for the copied CollectOSS/GrimoireLab/Graal Python blocks.

The copied packages keep their native SQL, event and subprocess boundaries.
This module is deliberately a small bridge for fixture/raw-row replay and for
embedding deployments that already provide a CollectOSS database session.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .activity_analyzer import ACTIVITY_POLICY_VERSION, ActivityAnalyzer
from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    Limitation,
    MetricValue,
)
from .forge_adapter import RawFact
from .issues_analyzer import ISSUES_ANALYZER_VERSION, IssuesAnalyzer
from .process import workspace_root

log = structlog.get_logger("chaoss.metric")

COLLECTOSS_COMMIT = "339edc520e79dd1728ca19255d94a05a4a107df1"
PERCEVAL_COMMIT = "cb07eaafa4c67561ca24ca8f9bb96783c312b5aa9"
GRAAL_COMMIT = "23ebfd0fa5249cc8e84b1992da3b26b15c0cd8f0"

CHAOSS_ACTIVITY_ID = "chaoss.activity"
CHAOSS_ISSUES_PRS_ID = "chaoss.issues_prs"
CHAOSS_RELEASES_ID = "chaoss.releases"
CHAOSS_DEPENDENCIES_ID = "chaoss.dependencies"
GRAAL_EXTERNAL_ID = "graal.external_tools"


@dataclass(frozen=True)
class MetricSource:
    """Metadata and a lazy callable for one copied CollectOSS metric."""

    metric_id: str
    module: str
    function_name: str
    category: str
    dimensions: tuple[str, ...]
    version: str = COLLECTOSS_COMMIT

    def load(self) -> Callable[..., Any] | None:
        try:
            _collectoss_source()
            module = importlib.import_module(f"collectoss.api.metrics.{self.module}")
            function = getattr(module, self.function_name)
            return function if callable(function) else None
        except (ImportError, AttributeError, OSError) as exc:
            log.warning("metric_source_unavailable metric_id=%s error_type=%s", self.metric_id, type(exc).__name__)
            return None


METRIC_SOURCES: tuple[MetricSource, ...] = (
    MetricSource("committers", "commit", "committers", "activity", ("commits", "contributors")),
    MetricSource("code_changes", "repo_meta", "code_changes", "activity", ("commits", "churn")),
    MetricSource("contributors", "contributor", "contributors", "activity", ("community", "contributors")),
    MetricSource("issues_first_time_opened", "issue", "issues_first_time_opened", "issues", ("issues", "community")),
    MetricSource("pull_requests_new", "pull_request", "pull_requests_new", "issues_prs", ("pull_requests", "delivery")),
    MetricSource("releases", "release", "releases", "releases", ("releases", "delivery")),
    MetricSource("deps", "deps", "deps", "dependencies", ("dependencies", "security")),
    MetricSource("libyear", "deps", "libyear", "dependencies", ("dependencies", "freshness")),
)

GROUP_METRICS = {
    CHAOSS_ACTIVITY_ID: frozenset({"committers", "code_changes", "contributors"}),
    CHAOSS_ISSUES_PRS_ID: frozenset({"issues_first_time_opened", "pull_requests_new"}),
    CHAOSS_RELEASES_ID: frozenset({"releases"}),
    CHAOSS_DEPENDENCIES_ID: frozenset({"deps", "libyear"}),
}


def _canonical_metric_dimension(source: MetricSource, analyzer_id: str) -> str:
    if analyzer_id == CHAOSS_DEPENDENCIES_ID:
        return "dependencies"
    if analyzer_id in {CHAOSS_RELEASES_ID, CHAOSS_ISSUES_PRS_ID}:
        return "delivery"
    if "community" in source.dimensions or "contributors" in source.dimensions:
        return "community"
    if "churn" in source.dimensions or "commits" in source.dimensions:
        return "history"
    return "community"


DEFINITIONS = {
    CHAOSS_ACTIVITY_ID: AnalyzerDefinition(
        id=CHAOSS_ACTIVITY_ID,
        version=ACTIVITY_POLICY_VERSION,
        category="chaoss-activity",
        dimensions=("activity", "community", "churn"),
        requires=("chaoss:events",),
        phase=60,
        cost=35,
        timeout=60,
        cache_policy="read_write",
        source_commit=COLLECTOSS_COMMIT,
        enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
    ),
    CHAOSS_ISSUES_PRS_ID: AnalyzerDefinition(
        id=CHAOSS_ISSUES_PRS_ID,
        version=ISSUES_ANALYZER_VERSION,
        category="chaoss-issues-prs",
        dimensions=("issues", "pull_requests", "review", "delivery"),
        requires=("chaoss:events",),
        phase=60,
        cost=40,
        timeout=60,
        cache_policy="read_write",
        source_commit=COLLECTOSS_COMMIT,
        enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
    ),
    CHAOSS_RELEASES_ID: AnalyzerDefinition(
        id=CHAOSS_RELEASES_ID,
        version="pinned",
        category="chaoss-releases",
        dimensions=("releases", "delivery"),
        requires=("chaoss:events",),
        phase=60,
        cost=30,
        timeout=60,
        cache_policy="read_write",
        source_commit=COLLECTOSS_COMMIT,
        enabled_by_mode=("full", "offline", "backfill"),
    ),
    CHAOSS_DEPENDENCIES_ID: AnalyzerDefinition(
        id=CHAOSS_DEPENDENCIES_ID,
        version="pinned",
        category="chaoss-dependencies",
        dimensions=("dependencies", "security", "freshness"),
        requires=("chaoss:events",),
        phase=60,
        cost=45,
        timeout=60,
        cache_policy="read_write",
        source_commit=COLLECTOSS_COMMIT,
        enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
    ),
    GRAAL_EXTERNAL_ID: AnalyzerDefinition(
        id=GRAAL_EXTERNAL_ID,
        version="pinned",
        category="external-quality-tools",
        dimensions=("code_quality", "security", "dependencies"),
        requires=("local_scan", "tool:graal"),
        phase=65,
        cost=55,
        timeout=120,
        cache_policy="read_write",
        source_commit=GRAAL_COMMIT,
        enabled_by_mode=("full", "diff", "backfill"),
    ),
}
GRAAL_EXTERNAL_DEFINITION = DEFINITIONS[GRAAL_EXTERNAL_ID]


def _collectoss_source() -> Path:
    source = workspace_root() / "vendor" / "collectoss"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def _graal_source() -> Path:
    source = workspace_root() / "vendor" / "chaoss" / "graal"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def available_metric_sources() -> tuple[str, ...]:
    """Return copied metric IDs whose native modules can be imported."""
    return tuple(source.metric_id for source in METRIC_SOURCES if source.load() is not None)


def available_graal_analyzers() -> tuple[str, ...]:
    names = ("lizard", "scc", "pylint", "scancode", "bandit", "reverse")
    available: list[str] = []
    for name in names:
        try:
            _graal_source()
            importlib.import_module(f"graal.backends.core.analyzers.{name}")
            available.append(name)
        except (ImportError, AttributeError, OSError):
            continue
    return tuple(available)


def _utc(value: object, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
        except ValueError:
            pass
    return fallback


def _stable_id(row: dict[str, Any], metric_id: str, index: int) -> str:
    for key in ("id", "event_id", "cmt_hash", "issue_id", "pr_id", "release_id", "sha"):
        if row.get(key) not in (None, ""):
            return str(row[key])
    raw = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return f"{metric_id}:{hashlib.sha256(f'{index}:{raw}'.encode()).hexdigest()[:20]}"


def normalize_rows(context: AnalyzerContext, rows_by_metric: dict[str, Any], *, window: str = "all") -> tuple[RawFact, ...]:
    facts: list[RawFact] = []
    for metric_id, rows in rows_by_metric.items():
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            facts.append(
                RawFact(
                    source="collectoss",
                    repo_id=context.repo_id,
                    event_type=str(row.get("event_type") or row.get("type") or metric_id),
                    stable_event_id=_stable_id(row, metric_id, index),
                    payload=dict(row),
                    updated_at=_utc(row.get("timestamp") or row.get("created_at") or row.get("date"), fallback=context.as_of_ts),
                    window_start=_utc(row.get("window_start"), fallback=context.as_of_ts),
                    window_end=_utc(row.get("window_end"), fallback=context.as_of_ts),
                    cursor=str(row.get("cursor")) if row.get("cursor") else None,
                    permission_state=str(row.get("permission_state") or "granted"),
                    source_version=COLLECTOSS_COMMIT,
                )
            )
    log.info("rows_normalized repo_id=%s window=%s facts=%d", context.repo_id, window, len(facts))
    return tuple(facts)


def _evidence(context: AnalyzerContext, metric_id: str, index: int, row: dict[str, Any]) -> EvidenceRef:
    path = row.get("path") or row.get("file_path")
    return EvidenceRef(
        source="collectoss",
        source_commit=COLLECTOSS_COMMIT,
        path=str(path) if path else None,
        json_pointer=f"/metrics/{metric_id}/{index}",
        collected_at=context.as_of_ts,
    )


def _numeric_value(row: dict[str, Any]) -> tuple[float | int, str]:
    for key in ("value", "count", "total", "commits", "pull_requests", "issues", "libyear"):
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value, key
    return 1, "rows"


class ChaossAdapter:
    """Expose copied CollectOSS metric rows and materialized-view state."""

    def collect(self, context: AnalyzerContext, *, window: str = "all") -> tuple[RawFact, ...]:
        supplied = context.inventory.get("chaoss_rows")
        if not isinstance(supplied, dict):
            return ()
        return normalize_rows(context, supplied, window=window)

    def result(self, context: AnalyzerContext, *, analyzer_id: str) -> AnalyzerResult:
        facts = self.collect(context, window=str(context.inventory.get("metric_window") or "all"))
        rows = context.inventory.get("chaoss_rows") if isinstance(context.inventory.get("chaoss_rows"), dict) else {}
        sources = {source.metric_id: source for source in METRIC_SOURCES}
        metrics: list[MetricValue] = []
        evidence: list[EvidenceRef] = []
        for metric_id, metric_rows in sorted(rows.items()):
            if analyzer_id in GROUP_METRICS and metric_id not in GROUP_METRICS[analyzer_id]:
                continue
            source = sources.get(metric_id)
            if source is None or not isinstance(metric_rows, list):
                continue
            numeric_values: list[float | int] = []
            unit = "rows"
            for index, row in enumerate(metric_rows):
                if not isinstance(row, dict):
                    continue
                value, unit = _numeric_value(row)
                numeric_values.append(value)
                evidence.append(_evidence(context, metric_id, index, row))
            if not numeric_values:
                continue
            total = sum(numeric_values)
            ref = evidence[-1]
            metrics.append(
                MetricValue(
                    name=f"chaoss:{metric_id}",
                    dimension=_canonical_metric_dimension(source, analyzer_id),
                    value=total,
                    unit=unit,
                    population=len(numeric_values),
                    denominator=len(numeric_values),
                    evidence_refs=(ref,),
                )
            )

        stale_views = [str(view) for view in (context.inventory.get("stale_materialized_views") or ())]
        warnings = list(context.inventory.get("chaoss_warnings") or ())
        warnings.extend(f"Materialized view is stale: {view}" for view in stale_views)
        findings = tuple(
            Finding(
                id=f"{analyzer_id}:warning:{index}",
                analyzer_id=analyzer_id,
                subject="chaoss-source",
                dimension="community" if analyzer_id == CHAOSS_ACTIVITY_ID else "dependencies",
                severity="medium",
                confidence=1.0,
                reason=warning,
                evidence_refs=(EvidenceRef(source="collectoss", source_commit=COLLECTOSS_COMMIT, json_pointer="/warnings", collected_at=context.as_of_ts),),
                remediation="Refresh the CollectOSS materialized view or provide the missing metric source.",
            )
            for index, warning in enumerate(warnings)
        )
        status = AnalyzerStatus.INCONCLUSIVE if not metrics and not facts else AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS
        limitations = () if metrics else (Limitation(reason="No CollectOSS rows were available for this metric family", kind="insufficient_denominator"),)
        return AnalyzerResult(
            analyzer_id=analyzer_id,
            analyzer_version="pinned",
            status=status,
            metrics=tuple(metrics),
            findings=findings,
            evidence=tuple({ref.model_dump_json(): ref for ref in evidence}.values()),
            limitations=limitations,
            available_weight=float(len(metrics)),
            total_weight=float(len(metrics)),
            raw_payload_ref=f"collectoss://{hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()}",
            source_versions={"collectoss": COLLECTOSS_COMMIT, "perceval": PERCEVAL_COMMIT},
            diagnostics={
                "metric_window": context.inventory.get("metric_window") or "all",
                "raw_fact_count": len(facts),
                "materialized_views": {view: "stale" for view in stale_views},
                "available_metric_sources": available_metric_sources(),
            },
        )


def graal_result(context: AnalyzerContext) -> AnalyzerResult:
    supplied = context.inventory.get("graal_results")
    if not isinstance(supplied, dict):
        return AnalyzerResult.skipped(GRAAL_EXTERNAL_DEFINITION, "No Graal analyzer outputs supplied", kind="missing_capability")
    metrics: list[MetricValue] = []
    findings: list[Finding] = []
    evidence: list[EvidenceRef] = []
    for analyzer_name, output in sorted(supplied.items()):
        if not isinstance(output, dict):
            continue
        for key, value in output.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                ref = EvidenceRef(source="graal", source_commit=GRAAL_COMMIT, json_pointer=f"/{analyzer_name}/{key}", collected_at=context.as_of_ts)
                metrics.append(MetricValue(name=f"graal:{analyzer_name}:{key}", dimension="security" if analyzer_name in {"bandit", "scancode"} else "code", value=value, evidence_refs=(ref,)))
                evidence.append(ref)
        for index, issue in enumerate(output.get("issues", [])):
            if not isinstance(issue, dict):
                continue
            ref = EvidenceRef(source="graal", source_commit=GRAAL_COMMIT, path=str(issue.get("path")) if issue.get("path") else None, line_start=int(issue["line"]) if str(issue.get("line", "")).isdigit() else None, line_end=int(issue["line"]) if str(issue.get("line", "")).isdigit() else None, json_pointer=f"/{analyzer_name}/issues/{index}", collected_at=context.as_of_ts)
            evidence.append(ref)
            findings.append(Finding(id=f"{GRAAL_EXTERNAL_ID}:{analyzer_name}:{index}", analyzer_id=GRAAL_EXTERNAL_ID, subject=str(issue.get("rule") or analyzer_name), dimension="security" if analyzer_name in {"bandit", "scancode"} else "code_quality", severity=str(issue.get("severity") or "medium"), confidence=1.0, reason=str(issue.get("message") or "Graal analyzer issue"), evidence_refs=(ref,), remediation=str(issue.get("remediation") or "Review and remediate the Graal analyzer issue.")))  # type: ignore[arg-type]
    status = AnalyzerStatus.FAIL if any(item.severity == "critical" for item in findings) else AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS if metrics else AnalyzerStatus.INCONCLUSIVE
    return AnalyzerResult(analyzer_id=GRAAL_EXTERNAL_ID, analyzer_version="pinned", status=status, metrics=tuple(metrics), findings=tuple(findings), evidence=tuple(evidence), available_weight=float(len(metrics)), total_weight=float(len(metrics)), raw_payload_ref=f"graal://{hashlib.sha256(json.dumps(supplied, sort_keys=True, default=str).encode()).hexdigest()}", source_versions={"graal": GRAAL_COMMIT}, diagnostics={"available_analyzers": available_graal_analyzers()})


_ADAPTER = ChaossAdapter()
_ACTIVITY_ANALYZER = ActivityAnalyzer()
_ISSUES_ANALYZER = IssuesAnalyzer()


def _metric_factory(analyzer_id: str) -> Callable[[AnalyzerContext], AnalyzerResult]:
    return lambda context: _ADAPTER.result(context, analyzer_id=analyzer_id)


def activity_adapter(context: AnalyzerContext) -> AnalyzerResult:
    base_result = _ADAPTER.result(context, analyzer_id=CHAOSS_ACTIVITY_ID)
    return _ACTIVITY_ANALYZER.analyze(context, base_result)


def issues_prs_adapter(context: AnalyzerContext) -> AnalyzerResult:
    base_result = _ADAPTER.result(context, analyzer_id=CHAOSS_ISSUES_PRS_ID)
    return _ISSUES_ANALYZER.analyze(context, base_result)


def releases_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return _ADAPTER.result(context, analyzer_id=CHAOSS_RELEASES_ID)


def dependencies_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return _ADAPTER.result(context, analyzer_id=CHAOSS_DEPENDENCIES_ID)


def register_chaoss_adapters(registry: Any) -> None:
    entries = (
        (DEFINITIONS[CHAOSS_ACTIVITY_ID], activity_adapter),
        (DEFINITIONS[CHAOSS_ISSUES_PRS_ID], issues_prs_adapter),
        (DEFINITIONS[CHAOSS_RELEASES_ID], releases_adapter),
        (DEFINITIONS[CHAOSS_DEPENDENCIES_ID], dependencies_adapter),
        (DEFINITIONS[GRAAL_EXTERNAL_ID], graal_result),
    )
    for definition, factory in entries:
        if definition.id not in registry.ids():
            registry.register(definition, factory)


__all__ = [
    "CHAOSS_ACTIVITY_ID",
    "CHAOSS_DEPENDENCIES_ID",
    "CHAOSS_ISSUES_PRS_ID",
    "CHAOSS_RELEASES_ID",
    "DEFINITIONS",
    "GRAAL_EXTERNAL_ID",
    "METRIC_SOURCES",
    "ChaossAdapter",
    "MetricSource",
    "RawFact",
    "activity_adapter",
    "available_graal_analyzers",
    "available_metric_sources",
    "dependencies_adapter",
    "graal_result",
    "issues_prs_adapter",
    "normalize_rows",
    "register_chaoss_adapters",
    "releases_adapter",
]
