"""Format adapters for copied Go native analyzers.

The Go implementations own scanning and scoring. This module owns only
argv construction, JSON/CSV parsing and mapping into the shared contract.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import structlog

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
from .process import NativeProcess, ProcessOutput, workspace_root

log = structlog.get_logger("native.adapters")

SCORECARD_ID = "scorecard.local"
REPOHEALTH_ID = "repohealth.baseline"
CRITICALITY_ID = "criticality.importance"
QLTY_ID = "qlty.check"
SOKRATES_ID = "sokrates.analysis"

SCORECARD_DEFINITION = AnalyzerDefinition(
    id=SCORECARD_ID,
    version="pinned",
    category="security-ci",
    dimensions=("security", "ci", "governance"),
    requires=("local_scan", "tool:scorecard"),
    phase=30,
    cost=50,
    timeout=120,
    cache_policy="read_write",
    source_commit="f92023a3f77879f96e0c9c1305f289d755be4bb6",
    enabled_by_mode=("full", "diff", "backfill"),
)
REPOHEALTH_DEFINITION = AnalyzerDefinition(
    id=REPOHEALTH_ID,
    version="pinned",
    category="repository-hygiene",
    dimensions=("documentation", "tests", "ci", "dependencies", "security"),
    requires=("local_scan", "tool:repohealth"),
    phase=20,
    cost=25,
    timeout=120,
    cache_policy="read_write",
    source_commit="a62f96a00134e7f08541fa00dd962666222394f8",
    enabled_by_mode=("fast", "full", "offline", "diff", "backfill"),
)
CRITICALITY_DEFINITION = AnalyzerDefinition(
    id=CRITICALITY_ID,
    version="pinned",
    category="priority-context",
    dimensions=("priority", "blast_radius"),
    requires=("criticality_csv", "tool:criticality-score"),
    phase=40,
    cost=60,
    timeout=120,
    cache_policy="read_write",
    source_commit="0e76c6a99d865dddcbd89dff4117f0a54b1abfb8",
    enabled_by_mode=("full", "diff", "backfill"),
)
QLTY_DEFINITION = AnalyzerDefinition(
    id=QLTY_ID,
    version="pinned",
    category="static-quality",
    dimensions=("code_quality", "security", "tests"),
    requires=("local_scan", "tool:qlty"),
    phase=30,
    cost=40,
    timeout=120,
    cache_policy="read_write",
    source_commit="338acb3405a966151cd9e29685f2a8eb71d92434",
    enabled_by_mode=("full", "fast", "diff", "backfill"),
)
SOKRATES_DEFINITION = AnalyzerDefinition(
    id=SOKRATES_ID,
    version="pinned",
    category="structural-analysis",
    dimensions=("code_quality", "contributors", "dependencies", "duplication", "churn"),
    requires=("local_scan", "tool:sokrates"),
    phase=35,
    cost=70,
    timeout=180,
    cache_policy="read_write",
    source_commit="f400eb7235a755146e854a1bf4bd90cbe1ee5086",
    enabled_by_mode=("full", "backfill"),
)


def _raw_ref(tool_id: str, raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    return f"native://{tool_id}/{digest}"


def _number(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _evidence(context: AnalyzerContext, source: str, *, path: str | None = None, line: int | None = None) -> EvidenceRef:
    return EvidenceRef(
        source=source,
        source_commit=context.head_sha,
        path=path,
        line_start=line,
        line_end=line,
        collected_at=context.as_of_ts,
    )


def _location(item: Mapping[str, Any]) -> FindingLocation | None:
    path = item.get("path") or item.get("file") or item.get("file_path")
    line = item.get("lineNumber") or item.get("line") or item.get("line_start")
    if path is None and line is None:
        return None
    line_number = int(line) if _number(line) is not None and int(float(line)) > 0 else None
    return FindingLocation(path=str(path) if path is not None else None, line_start=line_number, line_end=line_number)


def _scorecard_detail_evidence(context: AnalyzerContext, detail: Mapping[str, Any]) -> EvidenceRef:
    path = detail.get("path") or detail.get("file") or detail.get("location")
    line_value = detail.get("lineNumber") or detail.get("line")
    line = int(float(line_value)) if _number(line_value) is not None and int(float(line_value)) > 0 else None
    return _evidence(context, SCORECARD_ID, path=str(path) if path else None, line=line)


def _scorecard_dimension(name: str) -> str:
    lowered = name.casefold().replace("_", "-")
    if any(token in lowered for token in ("vulnerab", "license", "security", "code-quality")):
        return "security" if any(token in lowered for token in ("vulnerab", "security")) else "code"
    if any(token in lowered for token in ("test", "fuzz")):
        return "tests"
    if any(token in lowered for token in ("branch", "review", "ci", "workflow", "signed")):
        return "delivery"
    return "community"


def _repohealth_dimension(category: object) -> str:
    normalized = str(category or "docs").casefold().replace("_", "-")
    return {
        "docs": "docs",
        "documentation": "docs",
        "tests": "tests",
        "test": "tests",
        "ci": "delivery",
        "cicd": "delivery",
        "delivery": "delivery",
        "deps": "dependencies",
        "dependencies": "dependencies",
        "security": "security",
        "community": "community",
        "activity": "history",
        "stats": "history",
    }.get(normalized, "docs")


def _repohealth_check_score(item: Mapping[str, Any], state: str) -> float | None:
    explicit = _number(item.get("score"))
    if explicit is not None:
        return max(0.0, min(100.0, explicit if explicit > 10 else explicit * 10.0))
    return {"full": 100.0, "partial": 50.0, "none": 0.0}.get(state)


def _qlty_level(value: object) -> str:
    level = str(value or "warning").lower()
    return {
        "error": "critical",
        "high": "critical",
        "warning": "medium",
        "medium": "medium",
        "note": "low",
        "info": "low",
        "low": "low",
    }.get(level, "medium")


def _qlty_cache_key(context: AnalyzerContext, tool_versions: set[str]) -> str:
    dirty_paths = context.inventory.get("dirty_paths") or context.inventory.get("changed_paths") or ()
    payload = {
        "tool_versions": sorted(tool_versions),
        "plugin_config_digest": context.config_digest or "<none>",
        "target_tree_sha": context.head_sha,
        "dirty_paths": sorted(str(path) for path in dirty_paths),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _qlty_location(item: Mapping[str, Any]) -> FindingLocation | None:
    location = item.get("location")
    if not isinstance(location, Mapping):
        locations = item.get("locations")
        location = locations[0] if isinstance(locations, list) and locations and isinstance(locations[0], Mapping) else None
    if isinstance(location, Mapping) and "physicalLocation" in location:
        location = location.get("physicalLocation")
    if not isinstance(location, Mapping):
        return None
    artifact = location.get("artifactLocation")
    path = artifact.get("uri") if isinstance(artifact, Mapping) else location.get("path")
    path = str(path) if path else None
    region = location.get("region")
    if not isinstance(region, Mapping):
        region = location.get("range")
    if not isinstance(region, Mapping):
        region = {}
    start = region.get("start") if isinstance(region.get("start"), Mapping) else region
    end = region.get("end") if isinstance(region.get("end"), Mapping) else region
    start_line = _number(start.get("startLine") or start.get("start_line") or start.get("line"))
    end_line = _number(end.get("endLine") or end.get("end_line") or end.get("line") or start_line)
    start = int(start_line) if start_line is not None and start_line > 0 else None
    end = int(end_line) if end_line is not None and end_line > 0 else start
    return FindingLocation(path=path, line_start=start, line_end=end) if path or start else None


def _qlty_evidence(
    context: AnalyzerContext,
    location: FindingLocation | None,
    *,
    tool_version: str | None = None,
    pointer: str | None = None,
    fingerprint: str | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        source=QLTY_ID,
        source_commit=context.head_sha,
        tool_version=tool_version,
        path=location.path if location else None,
        line_start=location.line_start if location else None,
        line_end=location.line_end if location else None,
        json_pointer=pointer,
        snippet_hash=fingerprint,
        collected_at=context.as_of_ts,
    )


def _qlty_finding(
    context: AnalyzerContext,
    item: Mapping[str, Any],
    *,
    tool_name: str,
    tool_version: str | None,
    pointer: str,
    rule_id: str,
    message: str,
    level: object,
    help_uri: str | None = None,
    fingerprint: str | None = None,
) -> Finding:
    location = _qlty_location(item)
    evidence = _qlty_evidence(context, location, tool_version=tool_version, pointer=pointer, fingerprint=fingerprint)
    stable_suffix = fingerprint or f"{location.path if location else ''}:{location.line_start if location else ''}:{message}"
    severity = _qlty_level(level)
    return Finding(
        id=f"{QLTY_ID}:{tool_name}:{rule_id}:{hashlib.sha256(stable_suffix.encode()).hexdigest()[:16]}",
        analyzer_id=QLTY_ID,
        subject=rule_id or tool_name,
        dimension="security" if any(part in f"{rule_id} {message}".lower() for part in ("security", "secret", "vuln")) else "code_quality",
        severity=severity,  # type: ignore[arg-type]
        confidence=1.0,
        reason=message or "Qlty reported an issue",
        evidence_refs=(evidence,),
        location=location,
        remediation=help_uri,
    )


def parse_qlty(payload: Any, context: AnalyzerContext, *, raw_ref: str = "native://qlty/input") -> AnalyzerResult:
    """Parse Qlty's native SARIF and rdjson contracts without re-running plugins."""
    findings: list[Finding] = []
    evidence: list[EvidenceRef] = []
    tools: set[str] = set()
    tool_versions: set[str] = set()
    parser_format: str
    try:
        if isinstance(payload, Mapping) and isinstance(payload.get("runs"), list):
            parser_format = "sarif"
            for run_index, run in enumerate(payload["runs"]):
                if not isinstance(run, Mapping):
                    continue
                tool = run.get("tool") if isinstance(run.get("tool"), Mapping) else {}
                driver = tool.get("driver") if isinstance(tool, Mapping) and isinstance(tool.get("driver"), Mapping) else {}
                tool_name = str(driver.get("name") or "qlty")
                tool_version = str(driver.get("version")) if driver.get("version") else None
                tools.add(tool_name)
                if tool_version:
                    tool_versions.add(tool_version)
                rules = {
                    str(rule.get("id")): rule
                    for rule in (driver.get("rules") or [])
                    if isinstance(rule, Mapping) and rule.get("id")
                }
                for result_index, item in enumerate(run.get("results") or []):
                    if not isinstance(item, Mapping):
                        continue
                    rule_id = str(item.get("ruleId") or "unknown")
                    rule = rules.get(rule_id, {})
                    fingerprints = item.get("partialFingerprints")
                    fingerprint = next(iter(fingerprints.values()), None) if isinstance(fingerprints, Mapping) and fingerprints else None
                    finding = _qlty_finding(
                        context,
                        item,
                        tool_name=tool_name,
                        tool_version=tool_version,
                        pointer=f"/runs/{run_index}/results/{result_index}",
                        rule_id=rule_id,
                        message=str((item.get("message") or {}).get("text") if isinstance(item.get("message"), Mapping) else item.get("message") or ""),
                        level=item.get("level") or (rule.get("defaultConfiguration") or {}).get("level") if isinstance(rule.get("defaultConfiguration"), Mapping) else item.get("level"),
                        help_uri=str(rule.get("helpUri")) if rule.get("helpUri") else None,
                        fingerprint=str(fingerprint) if fingerprint else None,
                    )
                    findings.append(finding)
                    evidence.extend(finding.evidence_refs)
        elif isinstance(payload, Mapping) and isinstance(payload.get("diagnostics"), list):
            parser_format = "rdjson"
            default_severity = payload.get("severity")
            source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
            tool_name = str(source.get("name") or "qlty")
            tools.add(tool_name)
            for index, diagnostic in enumerate(payload["diagnostics"]):
                if not isinstance(diagnostic, Mapping):
                    continue
                code = diagnostic.get("code") if isinstance(diagnostic.get("code"), Mapping) else {}
                rule_id = str(code.get("value") or "unknown")
                finding = _qlty_finding(
                    context,
                    diagnostic,
                    tool_name=tool_name,
                    tool_version=None,
                    pointer=f"/diagnostics/{index}",
                    rule_id=rule_id,
                    message=str(diagnostic.get("message") or ""),
                    level=diagnostic.get("severity") or default_severity,
                    help_uri=str(code.get("url")) if code.get("url") else None,
                    fingerprint=str(diagnostic.get("fingerprint")) if diagnostic.get("fingerprint") else None,
                )
                findings.append(finding)
                evidence.extend(finding.evidence_refs)
        elif isinstance(payload, list):
            parser_format = "native-json"
            for index, item in enumerate(payload):
                if not isinstance(item, Mapping):
                    continue
                finding = _qlty_finding(
                    context,
                    item,
                    tool_name=str(item.get("tool") or "qlty"),
                    tool_version=str(item.get("tool_version")) if item.get("tool_version") else None,
                    pointer=f"/{index}",
                    rule_id=str(item.get("ruleKey") or item.get("rule_key") or item.get("check_id") or "unknown"),
                    message=str(item.get("message") or item.get("description") or ""),
                    level=item.get("level") or item.get("severity"),
                    help_uri=str(item.get("documentationUrl")) if item.get("documentationUrl") else None,
                    fingerprint=str(item.get("fingerprint")) if item.get("fingerprint") else None,
                )
                if item.get("tool_version"):
                    tool_versions.add(str(item["tool_version"]))
                findings.append(finding)
                evidence.extend(finding.evidence_refs)
        else:
            return AnalyzerResult(
                analyzer_id=QLTY_ID,
                analyzer_version="pinned",
                status=AnalyzerStatus.ERROR,
                limitations=(Limitation(reason="Qlty output is not SARIF, rdjson or native JSON", kind="error"),),
                raw_payload_ref=raw_ref,
            )
    except (TypeError, ValueError, AttributeError) as exc:
        return AnalyzerResult(
            analyzer_id=QLTY_ID,
            analyzer_version="pinned",
            status=AnalyzerStatus.ERROR,
            limitations=(Limitation(reason=f"Qlty payload malformed: {type(exc).__name__}", kind="error"),),
            raw_payload_ref=raw_ref,
        )
    status = AnalyzerStatus.FAIL if any(item.severity == "critical" for item in findings) else AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS
    issue_metric = MetricValue(name="qlty_issue_count", dimension="code", value=len(findings), population=len(findings), evidence_refs=tuple(evidence[:1]))
    all_evidence = list(evidence) + list(issue_metric.evidence_refs)
    return AnalyzerResult(
        analyzer_id=QLTY_ID,
        analyzer_version="pinned",
        status=status,
        metrics=(issue_metric,),
        findings=tuple(findings),
        evidence=tuple({ref.model_dump_json(): ref for ref in all_evidence}.values()),
        available_weight=1,
        total_weight=1,
        raw_payload_ref=raw_ref,
        source_versions={
            "qlty_parser": parser_format,
            "qlty_tools": ",".join(sorted(tools)) or "qlty",
            "qlty_versions": ",".join(sorted(tool_versions)) or "unknown",
        },
        cache_hit=bool(context.inventory.get("qlty_cache_hit", False)),
        diagnostics={
            "parser": parser_format,
            "tool_count": len(tools),
            "cache_key": _qlty_cache_key(context, tool_versions),
            "cache_provenance": {
                "target_tree_sha": context.head_sha,
                "dirty_paths": sorted(str(path) for path in (context.inventory.get("dirty_paths") or context.inventory.get("changed_paths") or ())),
                "plugin_config_digest": context.config_digest,
            },
        },
    )


def _sokrates_value(item: Mapping[str, Any], *names: str) -> object:
    for name in names:
        if name in item:
            return item[name]
    return None


def _sokrates_ref(
    context: AnalyzerContext,
    pointer: str,
    *,
    path: str = "data/analysisResults.json",
    line: int | None = None,
    confidence: float = 1.0,
) -> EvidenceRef:
    return EvidenceRef(
        source=SOKRATES_ID,
        source_commit=context.head_sha,
        path=path,
        line_start=line,
        line_end=line,
        json_pointer=pointer,
        collected_at=context.as_of_ts,
        confidence=confidence,
    )


def _sokrates_metric(
    context: AnalyzerContext,
    metrics: list[MetricValue],
    name: str,
    value: object,
    pointer: str,
    *,
    unit: str | None = None,
    population: int | None = None,
    denominator: int | None = None,
) -> None:
    numeric = _number(value)
    if numeric is None and not isinstance(value, (str, bool)):
        return
    metrics.append(
        MetricValue(
            name=name,
            dimension=(
                "history" if ":history:" in name or ":temporal_" in name
                else "community" if ":contributors" in name
                else "dependencies" if ":dependency" in name
                else "code"
            ),
            value=numeric if numeric is not None else value,
            unit=unit,
            population=population,
            denominator=denominator,
            evidence_refs=(_sokrates_ref(context, pointer),),
        )
    )
    

def _sokrates_dependency_edges(payload: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], str]]:
    edges: list[tuple[Mapping[str, Any], str]] = []
    direct = payload.get("dependencies") or payload.get("dependencyEdges") or payload.get("dependency_edges")
    if isinstance(direct, list):
        edges.extend((item, f"/dependencies/{index}") for index, item in enumerate(direct) if isinstance(item, Mapping))
    logical = payload.get("logicalDecompositionsAnalysisResults") or payload.get("logical_decompositions")
    if isinstance(logical, list):
        for group_index, group in enumerate(logical):
            if not isinstance(group, Mapping):
                continue
            nested = group.get("componentDependencies") or group.get("component_dependencies") or group.get("dependencies")
            if isinstance(nested, list):
                edges.extend(
                    (item, f"/logicalDecompositionsAnalysisResults/{group_index}/componentDependencies/{index}")
                    for index, item in enumerate(nested)
                    if isinstance(item, Mapping)
                )
    return edges


def parse_sokrates(payload: Any, context: AnalyzerContext, *, raw_ref: str = "native://sokrates/input") -> AnalyzerResult:
    """Read DataExporter JSON from Sokrates; Java owns the analysis algorithms."""
    if not isinstance(payload, Mapping):
        return AnalyzerResult(
            analyzer_id=SOKRATES_ID,
            analyzer_version="pinned",
            status=AnalyzerStatus.ERROR,
            limitations=(Limitation(reason="Sokrates export must be a JSON object", kind="error"),),
            raw_payload_ref=raw_ref,
        )

    metrics: list[MetricValue] = []
    findings: list[Finding] = []
    evidence: list[EvidenceRef] = []
    recognized = 0
    metric_list = payload.get("metricsList") or payload.get("metrics_list")
    if isinstance(metric_list, Mapping) and isinstance(metric_list.get("metrics"), list):
        for index, item in enumerate(metric_list["metrics"]):
            if not isinstance(item, Mapping):
                continue
            metric_id = item.get("id")
            value = item.get("value")
            if metric_id is None or value is None:
                continue
            _sokrates_metric(context, metrics, f"sokrates:{metric_id}", value, f"/metricsList/metrics/{index}")
            recognized += 1

    scope_keys = (
        "mainAspectAnalysisResults",
        "testAspectAnalysisResults",
        "generatedAspectAnalysisResults",
        "buildAndDeployAspectAnalysisResults",
        "otherAspectAnalysisResults",
        "main_aspect_analysis_results",
    )
    for scope_key in scope_keys:
        scope = payload.get(scope_key)
        if not isinstance(scope, Mapping):
            continue
        scope_name = str(scope.get("name") or scope_key.removesuffix("AspectAnalysisResults"))
        for field_name, unit in (("filesCount", "files"), ("linesOfCode", "lines"), ("numberOfRegexLineMatches", "matches")):
            value = scope.get(field_name)
            if value is None:
                continue
            _sokrates_metric(context, metrics, f"sokrates:{scope_name}:{field_name}", value, f"/{scope_key}/{field_name}", unit=unit)
            recognized += 1

    history = payload.get("filesHistoryAnalysisResults") or payload.get("files_history_analysis_results")
    if isinstance(history, Mapping):
        for field_name, unit in (
            ("filesWithoutCommitHistoryCount", "files"),
            ("filesWithoutCommitHistoryLinesOfCode", "lines"),
            ("daysBetweenFirstAndLastDate", "days"),
            ("activeDays", "days"),
            ("ageInDays", "days"),
        ):
            value = history.get(field_name)
            if value is None:
                continue
            _sokrates_metric(context, metrics, f"sokrates:history:{field_name}", value, f"/filesHistoryAnalysisResults/{field_name}", unit=unit)
            recognized += 1

    duplication = payload.get("duplicationAnalysisResults") or payload.get("duplication_analysis_results") or payload.get("duplication")
    overall = duplication.get("overallDuplication") if isinstance(duplication, Mapping) else None
    if not isinstance(overall, Mapping) and isinstance(duplication, Mapping):
        overall = duplication
    if isinstance(overall, Mapping):
        cleaned = _number(_sokrates_value(overall, "cleanedLinesOfCode", "cleaned_lines_of_code"))
        duplicate = _number(_sokrates_value(overall, "duplicatedLinesOfCode", "duplicated_lines_of_code"))
        if cleaned is not None and duplicate is not None and cleaned > 0:
            density = min(100.0, max(0.0, duplicate / cleaned * 100.0))
            ref = _sokrates_ref(context, "/duplicationAnalysisResults/overallDuplication")
            metrics.append(
                MetricValue(
                    name="sokrates:duplication_density",
                    dimension="code",
                    value=density,
                    unit="percent",
                    score=max(0.0, 100.0 - density),
                    population=int(duplicate),
                    denominator=int(cleaned),
                    evidence_refs=(ref,),
                )
            )
            recognized += 1
            if density > 10:
                severity = "critical" if density > 30 else "high" if density > 20 else "medium"
                findings.append(
                    Finding(
                        id=f"{SOKRATES_ID}:duplication:system",
                        analyzer_id=SOKRATES_ID,
                        subject="system",
                        dimension="duplication",
                        severity=severity,  # type: ignore[arg-type]
                        confidence=1.0,
                        reason=f"Sokrates reports {density:.2f}% duplicated LOC",
                        evidence_refs=(ref,),
                        remediation="Reduce repeated blocks or consolidate shared implementation.",
                        raw_impact=density,
                        applied_impact=density,
                    )
                )

    contributors_data = payload.get("contributorsAnalysisResults") or payload.get("contributors_analysis_results")
    contributors = contributors_data.get("contributors") if isinstance(contributors_data, Mapping) else payload.get("contributors")
    if isinstance(contributors, list):
        valid_contributors = [item for item in contributors if isinstance(item, Mapping)]
        commit_counts = sorted(
            (_number(_sokrates_value(item, "commitsCount", "commits_count")) or 0.0 for item in valid_contributors),
            reverse=True,
        )
        total_commits = sum(commit_counts)
        bus_factor = None
        if total_commits > 0:
            cumulative = 0.0
            for index, count in enumerate(commit_counts, start=1):
                cumulative += count
                if cumulative >= total_commits * 0.5:
                    bus_factor = index
                    break
        ref = _sokrates_ref(context, "/contributorsAnalysisResults/contributors")
        metrics.extend(
            (
                MetricValue(name="sokrates:contributors_count", value=len(valid_contributors), unit="contributors", evidence_refs=(ref,)),
                MetricValue(name="sokrates:commit_count", value=total_commits, unit="commits", evidence_refs=(ref,)),
            )
        )
        if bus_factor is not None:
            metrics.append(MetricValue(name="sokrates:bus_factor_50_percent", value=bus_factor, unit="contributors", evidence_refs=(ref,)))
            if bus_factor == 1:
                findings.append(
                    Finding(
                        id=f"{SOKRATES_ID}:bus-factor:1",
                        analyzer_id=SOKRATES_ID,
                        subject="contributors",
                        dimension="contributors",
                        severity="high",
                        confidence=1.0,
                        reason="One contributor accounts for at least 50% of Sokrates commit history",
                        evidence_refs=(ref,),
                        remediation="Spread ownership and review responsibility across more contributors.",
                    )
                )
        recognized += 1

    for edge, pointer in _sokrates_dependency_edges(payload):
        from_item = edge.get("from") if isinstance(edge.get("from"), Mapping) else {}
        to_item = edge.get("to") if isinstance(edge.get("to"), Mapping) else {}
        from_name = str(_sokrates_value(edge, "fromComponentName", "from_component", "from_name") or _sokrates_value(from_item, "anchor", "name") or "unknown")
        to_name = str(_sokrates_value(edge, "toComponentName", "to_component", "to_name") or _sokrates_value(to_item, "anchor", "name") or "unknown")
        edge_type = str(edge.get("edge_type") or edge.get("edgeType") or edge.get("type") or "inferred")
        confidence = 1.0 if edge_type in {"parsed", "imported"} else 0.6
        path = str(edge.get("path") or edge.get("sourcePath") or "data/analysisResults.json")
        line = _number(edge.get("line") or edge.get("line_start"))
        ref = _sokrates_ref(context, pointer, path=path, line=int(line) if line and line > 0 else None, confidence=confidence)
        evidence.append(ref)
        findings.append(
            Finding(
                id=f"{SOKRATES_ID}:dependency:{hashlib.sha256(f'{from_name}->{to_name}:{edge_type}'.encode()).hexdigest()[:16]}",
                analyzer_id=SOKRATES_ID,
                subject=f"{from_name}->{to_name}",
                dimension="dependencies",
                severity="info",
                confidence=confidence,
                reason=f"Sokrates dependency edge ({edge_type}) {from_name} -> {to_name}",
                evidence_refs=(ref,),
                location=FindingLocation(path=path, line_start=ref.line_start, line_end=ref.line_end),
            )
        )
        recognized += 1

    temporal = payload.get("temporalDependencies") or payload.get("temporal_dependencies") or payload.get("temporalDependenciesWindows")
    if isinstance(temporal, Mapping):
        for window, items in temporal.items():
            if not isinstance(items, list):
                continue
            _sokrates_metric(context, metrics, f"sokrates:temporal_dependencies:{window}", len(items), f"/temporalDependencies/{window}", unit="edges")
            recognized += 1

    export_version = str(payload.get("exportVersion") or payload.get("export_version") or payload.get("version") or "unknown")
    status = AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS if recognized else AnalyzerStatus.INCONCLUSIVE
    limitations = () if recognized else (Limitation(reason="Sokrates export has no supported DataExporter sections", kind="unsupported"),)
    all_evidence = list(evidence)
    for metric in metrics:
        all_evidence.extend(metric.evidence_refs)
    return AnalyzerResult(
        analyzer_id=SOKRATES_ID,
        analyzer_version=export_version,
        status=status,
        metrics=tuple(metrics),
        findings=tuple(findings),
        evidence=tuple({ref.model_dump_json(): ref for ref in all_evidence}.values()),
        limitations=limitations,
        available_weight=1 if recognized else 0,
        total_weight=1 if recognized else 0,
        raw_payload_ref=raw_ref,
        source_versions={"sokrates": SOKRATES_DEFINITION.source_commit or "", "export_version": export_version},
        diagnostics={"recognized_sections": recognized, "duplication_aggregation": "upstream_unique_lines", "dependency_edge_types": sorted({finding.reason.split("(")[1].split(")")[0] for finding in findings if "dependency edge (" in finding.reason})},
    )


def parse_scorecard(payload: Mapping[str, Any], context: AnalyzerContext, *, raw_ref: str = "native://scorecard/input") -> AnalyzerResult:
    checks = payload.get("checks") or payload.get("results") or []
    if not isinstance(checks, list):
        return AnalyzerResult(
            analyzer_id=SCORECARD_ID,
            analyzer_version="pinned",
            status=AnalyzerStatus.ERROR,
            limitations=(Limitation(reason="Scorecard checks must be an array", kind="error"),),
            raw_payload_ref=raw_ref,
        )
    measured: list[float] = []
    metrics: list[MetricValue] = []
    findings: list[Finding] = []
    evidence: list[EvidenceRef] = []
    limitations: list[Limitation] = []
    for index, item in enumerate(checks):
        if not isinstance(item, Mapping):
            limitations.append(Limitation(reason=f"Scorecard check {index} is malformed", kind="error"))
            continue
        name = str(item.get("name") or item.get("id") or f"check-{index}")
        score = _number(item.get("score"))
        if score is None:
            limitations.append(Limitation(reason=f"Scorecard check {name} has no score", kind="error"))
            continue
        details = item.get("details") or []
        detail_items = details if isinstance(details, list) else []
        refs = tuple(
            _scorecard_detail_evidence(context, detail)
            for detail in detail_items
            if isinstance(detail, Mapping)
        )
        evidence.extend(refs)
        if score < 0:
            limitations.append(Limitation(reason=f"Scorecard check {name} is inconclusive", kind="insufficient_denominator"))
            continue
        measured.append(score)
        dimension = _scorecard_dimension(name)
        metrics.append(
            MetricValue(
                name=f"scorecard:check:{name.casefold().replace(' ', '-')}",
                dimension=dimension,
                value=score,
                unit="score_0_10",
                score=max(0.0, min(100.0, score * 10.0)),
                population=1,
                denominator=1,
                evidence_refs=refs or (_evidence(context, SCORECARD_ID),),
            )
        )
        evidence.extend(refs or (_evidence(context, SCORECARD_ID),))
        if score >= 10:
            continue
        severity = "critical" if score <= 2 else "high" if score <= 5 else "medium" if score <= 8 else "low"
        reason = str(item.get("reason") or item.get("details") or f"Scorecard score {score:g}/10")
        ref = refs[0] if refs else _evidence(context, SCORECARD_ID)
        location = _location(item)
        if location is None and detail_items and isinstance(detail_items[0], Mapping):
            location = _location(detail_items[0])
        findings.append(
            Finding(
                id=f"{SCORECARD_ID}:{name}",
                analyzer_id=SCORECARD_ID,
                subject=name,
                dimension=dimension,
                severity=severity,  # type: ignore[arg-type]
                confidence=ref.confidence,
                reason=reason,
                evidence_refs=refs or (ref,),
                location=location,
                remediation=str(item.get("remediation") or item.get("suggestion") or "Review and remediate the Scorecard check."),
                raw_impact=10.0 - score,
                applied_impact=10.0 - score,
            )
        )
    if not measured:
        status = AnalyzerStatus.INCONCLUSIVE
        score = None
    elif any(_number(item.get("score")) == 0 for item in checks if isinstance(item, Mapping)):
        status = AnalyzerStatus.FAIL
        score = sum(measured) / len(measured) * 10.0
    elif findings:
        status = AnalyzerStatus.WARN
        score = sum(measured) / len(measured) * 10.0
    else:
        status = AnalyzerStatus.PASS
        score = sum(measured) / len(measured) * 10.0
    return AnalyzerResult(
        analyzer_id=SCORECARD_ID,
        analyzer_version=str(payload.get("version") or "pinned"),
        status=status,
        score=score,
        score_dimension="security",
        metrics=tuple(metrics),
        findings=tuple(findings),
        evidence=tuple({ref.model_dump_json(): ref for ref in evidence}.values()),
        limitations=tuple(limitations),
        available_weight=float(len(measured)),
        total_weight=float(len(checks)),
        raw_payload_ref=raw_ref,
        source_versions={"scorecard": str(payload.get("version") or "pinned"), "source_commit": SCORECARD_DEFINITION.source_commit or ""},
    )


def parse_repohealth(payload: Mapping[str, Any], context: AnalyzerContext, *, raw_ref: str = "native://repohealth/input") -> AnalyzerResult:
    checks = payload.get("checks") or []
    if not isinstance(checks, list):
        return AnalyzerResult(
            analyzer_id=REPOHEALTH_ID,
            analyzer_version=str(payload.get("version") or "pinned"),
            status=AnalyzerStatus.ERROR,
            limitations=(Limitation(reason="RepoHealth checks must be an array", kind="error"),),
            raw_payload_ref=raw_ref,
        )
    findings: list[Finding] = []
    evidence: list[EvidenceRef] = []
    metrics: list[MetricValue] = []
    suggestions = {
        str(item.get("check_id")): item
        for item in payload.get("suggestions", [])
        if isinstance(item, Mapping) and item.get("check_id")
    }
    measured = 0
    for index, item in enumerate(checks):
        if not isinstance(item, Mapping):
            continue
        check_id = str(item.get("id") or item.get("name") or f"check-{index}")
        state = str(item.get("status") or "none").lower()
        if state == "skipped":
            continue
        measured += 1
        ref = _evidence(context, REPOHEALTH_ID, path=str(item.get("path")) if item.get("path") else None)
        evidence.append(ref)
        dimension = _repohealth_dimension(item.get("category"))
        check_score = _repohealth_check_score(item, state)
        metrics.append(
            MetricValue(
                name=f"repohealth:check:{check_id}",
                dimension=dimension,
                value=state,
                unit="check_state",
                score=check_score,
                population=1,
                denominator=1 if check_score is not None else None,
                evidence_refs=(ref,),
            )
        )
        if state == "full":
            continue
        suggestion = suggestions.get(check_id) or {}
        remediation = item.get("suggestion") or suggestion.get("message") or "Bring this repository-health check to full status."
        impact = _number(item.get("impact"))
        if impact is None:
            impact = _number(suggestion.get("impact"))
        severity = "critical" if state == "none" else "medium"
        findings.append(
            Finding(
                id=f"{REPOHEALTH_ID}:{check_id}",
                analyzer_id=REPOHEALTH_ID,
                subject=check_id,
                dimension=str(item.get("category") or "repository-hygiene"),
                severity=severity,  # type: ignore[arg-type]
                confidence=1.0,
                reason=str(item.get("details") or f"RepoHealth check is {state}"),
                evidence_refs=(ref,),
                location=FindingLocation(path=ref.path) if ref.path else None,
                remediation=str(remediation),
                raw_impact=impact,
                applied_impact=impact,
            )
        )
    score = _number(payload.get("score"))
    status = AnalyzerStatus.INCONCLUSIVE if score is None else AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS
    return AnalyzerResult(
        analyzer_id=REPOHEALTH_ID,
        analyzer_version=str(payload.get("version") or "pinned"),
        status=status,
        score=score,
        score_dimension="docs",
        metrics=tuple(metrics),
        findings=tuple(findings),
        evidence=tuple(evidence),
        limitations=(),
        available_weight=float(measured),
        total_weight=float(len(checks)),
        raw_payload_ref=raw_ref,
        source_versions={"repohealth": str(payload.get("version") or "pinned"), "source_commit": REPOHEALTH_DEFINITION.source_commit or ""},
    )


def parse_criticality_csv(raw_csv: str, context: AnalyzerContext, *, raw_ref: str = "native://criticality/input") -> AnalyzerResult:
    reader = csv.DictReader(io.StringIO(raw_csv))
    if not reader.fieldnames:
        return AnalyzerResult.insufficient_denominator(CRITICALITY_DEFINITION, "Criticality output has no CSV header", total_weight=1)
    rows = list(reader)
    if not rows:
        return AnalyzerResult.insufficient_denominator(CRITICALITY_DEFINITION, "Criticality output has no records", total_weight=1)
    row = rows[0]
    score_key = next((key for key in row if key and key.lower() in {"default_score", "score", "criticality_score"}), None)
    score = _number(row.get(score_key)) if score_key else None
    signals: dict[str, float | str] = {}
    metrics: list[MetricValue] = []
    ref = _evidence(context, CRITICALITY_ID)
    for key, value in row.items():
        if not key or key == score_key or value in (None, ""):
            continue
        numeric = _number(value)
        if numeric is None:
            signals[key] = str(value)
            continue
        signals[key] = numeric
        metrics.append(MetricValue(name=f"criticality_signal:{key}", value=numeric, evidence_refs=(ref,)))
    if score is None:
        return AnalyzerResult.insufficient_denominator(CRITICALITY_DEFINITION, "Criticality score column is absent or invalid", total_weight=1)
    return AnalyzerResult(
        analyzer_id=CRITICALITY_ID,
        analyzer_version="pinned",
        status=AnalyzerStatus.PASS,
        metrics=tuple(metrics),
        evidence=(ref,),
        available_weight=1,
        total_weight=1,
        raw_payload_ref=raw_ref,
        source_versions={"criticality_score": CRITICALITY_DEFINITION.source_commit or ""},
        diagnostics={"priority_context": {"criticality_score": score, "signals": signals}},
    )


def _tool_entry(tool_id: str) -> dict[str, Any]:
    import yaml

    config_path = workspace_root() / "config" / "analyzers" / "native-tools.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return dict(payload["tools"][tool_id])


def _run_native(tool_id: str, context: AnalyzerContext, *, stdin: str | None = None) -> ProcessOutput:
    entry = _tool_entry(tool_id)
    root = workspace_root()
    configured = context.tool_paths.get(tool_id)
    candidates = [configured] if configured else []
    if not configured:
        candidates.extend([entry.get("executable_windows"), entry.get("executable")])
    executable = None
    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute() and (root / candidate_path).exists():
            candidate_path = root / candidate_path
        elif not candidate_path.is_absolute():
            candidate_path = Path(shutil.which(str(candidate_path)) or candidate_path)
        executable = candidate_path
        if executable.exists():
            break
    if executable is None or not executable.exists():
        return ProcessOutput(tool_id, None, "", "binary absent", 0)
    args: list[str] = []
    placeholders = {
        "{repo_path}": str(context.repo_path),
        "{head_sha}": context.head_sha,
        "{sokrates_config}": str(context.inventory.get("sokrates_config") or ""),
        "{sokrates_output}": str(context.inventory.get("sokrates_output") or ""),
        "{sokrates_jar}": str(context.inventory.get("sokrates_jar") or root / "bin" / "sokrates.jar"),
    }
    for raw_arg in entry.get("command", []):
        value = str(raw_arg)
        for placeholder, replacement in placeholders.items():
            value = value.replace(placeholder, replacement)
        if value.startswith("vendor/"):
            value = str(root / value)
        args.append(value)
    if tool_id == QLTY_ID and context.mode == "full" and "--all" not in args:
        args.insert(1 if args and args[0] == "check" else 0, "--all")
    return NativeProcess(output_cap=int(entry.get("max_output_bytes", 16 * 1024 * 1024))).run(
        tool_id,
        executable,
        args,
        context,
        timeout=float(entry.get("timeout", 120)),
        stdin=stdin,
    )


def _process_error(definition: AnalyzerDefinition, output: ProcessOutput) -> AnalyzerResult:
    kind = "timeout" if output.timed_out else "error"
    reason = "native process timed out" if output.timed_out else "native process failed"
    return AnalyzerResult(
        analyzer_id=definition.id,
        analyzer_version="pinned",
        status=AnalyzerStatus.ERROR,
        limitations=(Limitation(reason=reason, kind=kind),),  # type: ignore[arg-type]
        raw_payload_ref=_raw_ref(definition.id, output.stdout),
        diagnostics={"exit_code": output.exit_code, "truncated": output.truncated},
    )


def scorecard_adapter(context: AnalyzerContext) -> AnalyzerResult:
    output = _run_native(SCORECARD_ID, context)
    if output.exit_code is None or output.timed_out or output.truncated:
        return _process_error(SCORECARD_DEFINITION, output)
    try:
        payload = json.loads(output.stdout)
    except json.JSONDecodeError:
        return _process_error(SCORECARD_DEFINITION, output)
    result = parse_scorecard(payload, context, raw_ref=_raw_ref(SCORECARD_ID, output.stdout))
    if output.exit_code != 0 and result.status is not AnalyzerStatus.INCONCLUSIVE:
        result = result.model_copy(update={"diagnostics": {**result.diagnostics, "threshold_exit": output.exit_code}})
    return result


def repohealth_adapter(context: AnalyzerContext) -> AnalyzerResult:
    output = _run_native(REPOHEALTH_ID, context)
    if output.exit_code is None or output.timed_out or output.truncated:
        return _process_error(REPOHEALTH_DEFINITION, output)
    try:
        payload = json.loads(output.stdout)
    except json.JSONDecodeError:
        return _process_error(REPOHEALTH_DEFINITION, output)
    return parse_repohealth(payload, context, raw_ref=_raw_ref(REPOHEALTH_ID, output.stdout))


def criticality_adapter(context: AnalyzerContext) -> AnalyzerResult:
    raw_csv = str(context.inventory.get("criticality_csv") or "")
    output = _run_native(CRITICALITY_ID, context, stdin=raw_csv)
    if output.exit_code is None or output.timed_out or output.truncated:
        return _process_error(CRITICALITY_DEFINITION, output)
    return parse_criticality_csv(output.stdout, context, raw_ref=_raw_ref(CRITICALITY_ID, output.stdout))


def qlty_adapter(context: AnalyzerContext) -> AnalyzerResult:
    output = _run_native(QLTY_ID, context)
    if output.exit_code is None or output.timed_out or output.truncated:
        return _process_error(QLTY_DEFINITION, output)
    try:
        payload = json.loads(output.stdout)
    except json.JSONDecodeError:
        return _process_error(QLTY_DEFINITION, output)
    result = parse_qlty(payload, context, raw_ref=_raw_ref(QLTY_ID, output.stdout))
    if output.exit_code != 0 and result.status is not AnalyzerStatus.ERROR:
        result = result.model_copy(update={"diagnostics": {**result.diagnostics, "threshold_exit": output.exit_code}})
    return result


def _sokrates_snapshot_from_context(context: AnalyzerContext) -> tuple[Any, str] | None:
    snapshot = context.inventory.get("sokrates_export")
    if isinstance(snapshot, Mapping):
        raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        return snapshot, _raw_ref(SOKRATES_ID, raw)
    candidate = context.inventory.get("sokrates_export_path") or context.inventory.get("sokrates_analysis_results")
    if not candidate:
        return None
    path = Path(str(candidate))
    if not path.is_absolute():
        path = context.repo_path / path
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw), _raw_ref(SOKRATES_ID, raw)


def sokrates_adapter(context: AnalyzerContext) -> AnalyzerResult:
    try:
        snapshot = _sokrates_snapshot_from_context(context)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        snapshot = None
    if snapshot is not None:
        payload, raw_ref = snapshot
        return parse_sokrates(payload, context, raw_ref=raw_ref)
    output = _run_native(SOKRATES_ID, context)
    if output.exit_code is None or output.timed_out or output.truncated:
        return _process_error(SOKRATES_DEFINITION, output)
    try:
        payload = json.loads(output.stdout)
    except json.JSONDecodeError:
        return _process_error(SOKRATES_DEFINITION, output)
    result = parse_sokrates(payload, context, raw_ref=_raw_ref(SOKRATES_ID, output.stdout))
    if output.exit_code != 0:
        result = result.model_copy(update={"diagnostics": {**result.diagnostics, "threshold_exit": output.exit_code}})
    return result


def register_native_adapters(registry: Any) -> None:
    entries = (
        (SCORECARD_DEFINITION, scorecard_adapter),
        (REPOHEALTH_DEFINITION, repohealth_adapter),
        (CRITICALITY_DEFINITION, criticality_adapter),
        (QLTY_DEFINITION, qlty_adapter),
        (SOKRATES_DEFINITION, sokrates_adapter),
    )
    for definition, factory in entries:
        if definition.id not in registry.ids():
            registry.register(definition, factory)


__all__ = [
    "CRITICALITY_DEFINITION",
    "QLTY_DEFINITION",
    "REPOHEALTH_DEFINITION",
    "SCORECARD_DEFINITION",
    "SOKRATES_DEFINITION",
    "criticality_adapter",
    "parse_criticality_csv",
    "parse_qlty",
    "parse_repohealth",
    "parse_scorecard",
    "parse_sokrates",
    "qlty_adapter",
    "register_native_adapters",
    "repohealth_adapter",
    "scorecard_adapter",
    "sokrates_adapter",
]
