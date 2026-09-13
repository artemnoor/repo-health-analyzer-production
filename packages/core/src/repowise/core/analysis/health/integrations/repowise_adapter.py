"""Thin composition adapter for the copied RepoWise health/Git pipeline."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from typing import Any

import structlog

from repowise.core.analysis.health import HealthAnalyzer
from repowise.core.analysis.health.engine import HEALTH_ANALYZER_VERSION
from repowise.core.analysis.health.models import HealthReport
from repowise.core.ingestion.git_indexer import GitIndexer, GitIndexTier

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

log = structlog.get_logger("health.repowise")

REPOWISE_ANALYZER_ID = "repowise.health"
REPOWISE_DEFINITION = AnalyzerDefinition(
    id=REPOWISE_ANALYZER_ID,
    version=str(HEALTH_ANALYZER_VERSION),
    category="repository-health",
    dimensions=("defect", "maintainability", "performance"),
    requires=("local_scan",),
    supports=(),
    phase=10,
    cost=20,
    timeout=600,
    cache_policy="none",
    source_commit=None,
)


def _run_indexer(indexer: GitIndexer, repo_id: str) -> tuple[Any, list[dict[str, Any]]]:
    """Run the existing async indexer from the synchronous analyzer boundary."""
    return asyncio.run(indexer.index_repo(repo_id))


def _evidence(context: AnalyzerContext, path: str | None = None, *, line_start: int | None = None, line_end: int | None = None) -> EvidenceRef:
    return EvidenceRef(
        source=REPOWISE_ANALYZER_ID,
        source_commit=context.head_sha,
        tool_version=str(HEALTH_ANALYZER_VERSION),
        path=path,
        line_start=line_start,
        line_end=line_end,
        collected_at=context.as_of_ts,
    )


def _refactoring_action(suggestion: Any) -> str:
    """Render the existing structured refactoring plan as a stable action."""
    refactoring_type = str(getattr(suggestion, "refactoring_type", "refactor")).replace("_", " ")
    file_path = str(getattr(suggestion, "file_path", "the affected file"))
    target = str(getattr(suggestion, "target_symbol", ""))
    suffix = f"::{target}" if target else ""
    return f"Apply {refactoring_type} at {file_path}{suffix}."


def _map_report(context: AnalyzerContext, report: HealthReport, *, git_available: bool, git_tier: str) -> AnalyzerResult:
    evidence: dict[tuple[str | None, int | None, int | None], EvidenceRef] = {}

    def evidence_for(path: str | None, line_start: int | None = None, line_end: int | None = None) -> EvidenceRef:
        key = (path, line_start, line_end)
        evidence.setdefault(key, _evidence(context, path, line_start=line_start, line_end=line_end))
        return evidence[key]

    metrics: list[MetricValue] = []
    for metric in report.metrics:
        ref = evidence_for(metric.file_path)
        metrics.append(
            MetricValue(
                name=f"file_health:{metric.file_path}",
                dimension="code",
                value=metric.score,
                unit="score_0_10",
                score=max(0.0, min(100.0, float(metric.score) * 10.0)),
                population=max(0, int(metric.nloc or 0)),
                denominator=1,
                evidence_refs=(ref,),
            )
        )

    suggestions = list(report.refactoring_suggestions or [])
    findings: list[Finding] = []
    for index, finding in enumerate(report.findings):
        ref = evidence_for(finding.file_path, finding.line_start, finding.line_end)
        severity = getattr(finding.severity, "value", str(finding.severity)).lower()
        if severity not in {"info", "low", "medium", "high", "critical"}:
            severity = "medium"
        finding_id = ":".join(
            [
                REPOWISE_ANALYZER_ID,
                str(finding.biomarker_type),
                str(finding.file_path),
                str(finding.line_start or index),
            ]
        )
        suggestion = next(
            (
                item
                for item in suggestions
                if str(getattr(item, "file_path", "")) == str(finding.file_path)
                and str(getattr(item, "source_biomarker", "")) == str(finding.biomarker_type)
            ),
            None,
        )
        findings.append(
            Finding(
                id=finding_id,
                analyzer_id=REPOWISE_ANALYZER_ID,
                subject=finding.file_path,
                dimension=finding.dimension or "defect",
                severity=severity,  # type: ignore[arg-type]
                confidence=1.0,
                reason=finding.reason or str(finding.biomarker_type),
                evidence_refs=(ref,),
                location=FindingLocation(
                    path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    symbol=finding.function_name,
                ),
                remediation=(
                    _refactoring_action(suggestion)
                    if suggestion is not None
                    else "Review the reported RepoWise biomarker and apply the relevant refactoring."
                ),
                raw_impact=float(finding.health_impact),
                applied_impact=float(finding.health_impact),
            )
        )

    limitations: list[Limitation] = []
    if not git_available:
        limitations.append(Limitation(reason="Git history is unavailable", kind="missing_capability"))
    if not report.metrics:
        limitations.append(
            Limitation(
                reason="No measurable files were found for the selected population",
                kind="insufficient_denominator",
                affected_scope=context.scope,
            )
        )

    average = report.kpis.get("average_health")
    score = float(average) * 10.0 if isinstance(average, (int, float)) else None
    if not report.metrics:
        status = AnalyzerStatus.INCONCLUSIVE
    elif findings:
        status = AnalyzerStatus.WARN
    else:
        status = AnalyzerStatus.PASS

    total_weight = float(len(report.metrics))
    return AnalyzerResult(
        analyzer_id=REPOWISE_ANALYZER_ID,
        analyzer_version=str(HEALTH_ANALYZER_VERSION),
        status=status,
        score=score,
        metrics=tuple(metrics),
        findings=tuple(findings),
        evidence=tuple(evidence.values()),
        limitations=tuple(limitations),
        source_versions={"repowise-health": str(HEALTH_ANALYZER_VERSION), "git-tier": git_tier},
        available_weight=total_weight,
        total_weight=total_weight,
        diagnostics={
            "repo_id": context.repo_id,
            "head_sha": context.head_sha,
            "as_of_ts": context.as_of_ts.isoformat(),
            "mode": context.mode,
            "scope": context.scope,
            "git_tier": git_tier,
            "metric_count": len(metrics),
            "finding_count": len(findings),
            "refactoring_suggestion_count": len(suggestions),
            "evidence_count": len(evidence),
        },
    )


class RepoWiseAdapter:
    """Calls existing RepoWise objects and maps their report once."""

    definition = REPOWISE_DEFINITION

    def __init__(self) -> None:
        self.last_report: HealthReport | None = None

    @staticmethod
    def git_tier(mode: str) -> GitIndexTier:
        return GitIndexTier.ESSENTIAL if mode in {"fast", "offline"} else GitIndexTier.FULL

    def run(self, context: AnalyzerContext) -> AnalyzerResult:
        result, report = self.analyze(context)
        self.last_report = report
        return result

    def analyze(self, context: AnalyzerContext) -> tuple[AnalyzerResult, HealthReport]:
        inventory = context.inventory
        repo_path = Path(context.repo_path)
        parsed_files = list(inventory.get("parsed_files") or [])
        graph = inventory.get("graph")
        coverage_map = inventory.get("coverage_map") or {}
        git_meta_map = dict(inventory.get("git_meta_map") or {})
        git_tier = self.git_tier(context.mode)

        log.debug(
            "starting",
            repo_id=context.repo_id,
            head_sha=context.head_sha,
            mode=context.mode,
            scope=context.scope,
            parsed_files=len(parsed_files),
            git_tier=git_tier.value,
        )

        git_available = "git" in context.capabilities or (repo_path / ".git").exists()
        if not git_meta_map and git_available:
            indexer = GitIndexer(
                repo_path,
                tier=git_tier,
                exclude_patterns=list(inventory.get("exclude_patterns") or []),
            )
            _, metadata_list = _run_indexer(indexer, context.repo_id)
            git_meta_map = {str(item.get("file_path")): item for item in metadata_list if item.get("file_path")}
            log.info("git_index_finished repo_id=%s tier=%s files=%d", context.repo_id, git_tier.value, len(git_meta_map))
        elif not git_available:
            log.warning("git_unavailable repo_id=%s", context.repo_id)

        # Identity and temporal enrichment extend the public GitIndexer
        # metadata shape; HealthAnalyzer keeps consuming the same map and its
        # existing ownership/hotspot/prior-defect algorithms remain intact.
        if git_meta_map:
            from .identity_adapter import enrich_git_meta_map

            git_meta_map = enrich_git_meta_map(context, git_meta_map)

        analyzer = HealthAnalyzer(
            graph,
            git_meta_map=git_meta_map,
            parsed_files=parsed_files,
            coverage_map=coverage_map,
            community_label_map=inventory.get("community_label_map"),
            duplication_cache_dir=inventory.get("duplication_cache_dir") or (repo_path / ".repowise"),
            repo_root=repo_path,
        )
        report_config = inventory.get("health_config")
        if report_config is None:
            report_config = {}
        report = analyzer.analyze(
            report_config,
            changed_files=inventory.get("changed_files") if context.mode == "diff" else None,
            repo_function_mod_p80=inventory.get("repo_function_mod_p80"),
            duplication_files=inventory.get("duplication_files"),
        )
        # HealthAnalyzer is intentionally reused as-is, but its legacy report
        # timestamp is replaced at the composition boundary for replayability.
        report.repo_id = context.repo_id
        report.analyzed_at = context.as_of_ts.astimezone(UTC)
        result = _map_report(context, report, git_available=git_available, git_tier=git_tier.value)
        log.info(
            "health_finished repo_id=%s head_sha=%s tier=%s metrics=%d findings=%d score=%s",
            context.repo_id,
            context.head_sha,
            git_tier.value,
            len(report.metrics),
            len(report.findings),
            result.score,
        )
        return result, report


_DEFAULT_ADAPTER: RepoWiseAdapter | None = None


def register_repowise(registry: Any, adapter: RepoWiseAdapter | None = None) -> RepoWiseAdapter:
    """Register RepoWise once; useful for CLI and embedding applications."""
    global _DEFAULT_ADAPTER
    if REPOWISE_ANALYZER_ID not in registry.ids():
        _DEFAULT_ADAPTER = adapter or RepoWiseAdapter()
        registry.register(REPOWISE_DEFINITION, _DEFAULT_ADAPTER.run)
    elif _DEFAULT_ADAPTER is None:
        _DEFAULT_ADAPTER = adapter or RepoWiseAdapter()
    return _DEFAULT_ADAPTER


__all__ = [
    "REPOWISE_ANALYZER_ID",
    "REPOWISE_DEFINITION",
    "RepoWiseAdapter",
    "register_repowise",
]
