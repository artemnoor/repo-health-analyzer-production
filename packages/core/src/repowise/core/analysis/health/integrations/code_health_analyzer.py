"""Confidence-aware local Code Health scoring over normalized facts."""

from __future__ import annotations

import structlog

from .code_health_facts import (
    CodeHealthFacts,
    CodeHealthPolicy,
    CodeHealthStatus,
    SonarFacts,
    load_code_health_policy,
)
from .contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    MetricValue,
)

log = structlog.get_logger("health.code_health.analyzer")

CODE_HEALTH_ANALYZER_VERSION = "code-health-analyzer-v1"


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _metric(facts: SonarFacts | None, name: str) -> float | str | None:
    return facts.measures.get(name) if facts else None


def _inverse(value: float | None, good: float, bad: float) -> float | None:
    if value is None:
        return None
    if bad <= good:
        return None
    return max(0.0, min(100.0, 100.0 * (bad - value) / (bad - good)))


def _rating_score(value: object, policy: CodeHealthPolicy) -> float | None:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in policy.maintainability_rating_scores:
            return float(policy.maintainability_rating_scores[normalized])
        numeric = _number(normalized)
    else:
        numeric = _number(value)
    if numeric is None:
        return None
    letter = "ABCDE"[max(1, min(5, round(numeric))) - 1]
    return float(policy.maintainability_rating_scores.get(letter, 0.0))


def _severity(value: str | None) -> str:
    normalized = str(value or "").casefold()
    return {
        "blocker": "critical",
        "critical": "critical",
        "major": "high",
        "high": "high",
        "minor": "low",
        "low": "low",
        "info": "info",
    }.get(normalized, "medium")


def _concern_score(value: object) -> float:
    normalized = str(value or "").casefold()
    if normalized in {"critical", "4", "5"}:
        return 0.0
    if normalized in {"high", "3"}:
        return 25.0
    if normalized in {"medium", "2"}:
        return 60.0
    if normalized in {"low", "1"}:
        return 85.0
    return 100.0


def _evidence(context: AnalyzerContext, *, source: str, path: str | None = None, line: int | None = None, pointer: str | None = None, confidence: float = 1.0, tool_version: str | None = None) -> EvidenceRef:
    return EvidenceRef(
        source=source,
        source_commit=context.head_sha,
        tool_version=tool_version,
        path=path,
        line_start=line,
        line_end=line,
        json_pointer=pointer,
        collected_at=context.as_of_ts,
        confidence=max(0.0, min(1.0, confidence)),
        redaction="partial" if source in {"sonarqube", "git-sizer"} else "none",
    )


class CodeHealthAnalyzer:
    """Add one confidence-adjusted Code Health score to existing repowise.health."""

    def analyze(
        self,
        context: AnalyzerContext,
        facts: CodeHealthFacts,
        baseline: AnalyzerResult | None = None,
        *,
        policy: CodeHealthPolicy | None = None,
    ) -> AnalyzerResult:
        resolved = policy or load_code_health_policy()
        usable = self._has_usable_facts(facts)
        if not usable:
            return self._fallback(context, facts, baseline)

        components = self._components(facts, resolved)
        eligible_weight = sum(float(resolved.component_weights.get(name, 0.0)) for name, value in components.items() if value is not None)
        total_weight = sum(float(value) for value in resolved.component_weights.values())
        if eligible_weight <= 0:
            return self._fallback(context, facts, baseline)
        raw_score = sum(float(value) * float(resolved.component_weights.get(name, 0.0)) for name, value in components.items() if value is not None) / eligible_weight
        final_score = max(0.0, min(100.0, raw_score * facts.confidence))
        if facts.status is CodeHealthStatus.PARTIAL:
            final_score = min(final_score, resolved.partial_score_cap)

        evidence, findings = self._evidence_and_findings(context, facts)
        metrics = list(baseline.metrics if baseline else ())
        if baseline is not None:
            # Legacy per-file metrics remain observable but the single aggregate
            # score is now authoritative for this enriched result, including
            # runs where optional engines are unavailable.
            metrics = [metric.model_copy(update={"score": None}) for metric in metrics]
            log.info(
                "[FIX:code-health-score] demoted_baseline_metric_scores",
                repo_id=context.repo_id,
                metric_count=len(metrics),
            )
        metrics.extend(
            MetricValue(
                name=f"code_health:{name}",
                dimension="code",
                value=value,
                unit="score_0_100",
                score=None,
                population=1,
                denominator=1,
            )
            for name, value in sorted(components.items())
            if value is not None
        )
        metrics.extend(
            (
                MetricValue(name="code_health:coverage", dimension="code", value=facts.coverage, unit="ratio"),
                MetricValue(name="code_health:confidence", dimension="code", value=facts.confidence, unit="ratio"),
            )
        )
        limitations = list(baseline.limitations if baseline else ())
        limitations.extend(
            Limitation(reason=reason, kind="missing_capability" if "unavailable" in reason else "other", affected_scope=context.scope)
            for reason in facts.limitations
        )
        status = self._public_status(facts, final_score, findings, baseline)
        result = AnalyzerResult(
            analyzer_id=baseline.analyzer_id if baseline else "repowise.health",
            analyzer_version=baseline.analyzer_version if baseline else CODE_HEALTH_ANALYZER_VERSION,
            status=status,
            score=final_score if status not in {AnalyzerStatus.ERROR, AnalyzerStatus.SKIPPED} else None,
            score_dimension="code",
            metrics=tuple(metrics),
            findings=tuple([*(baseline.findings if baseline else ()), *findings]),
            evidence=tuple([*(baseline.evidence if baseline else ()), *evidence]),
            limitations=tuple(limitations),
            duration_ms=baseline.duration_ms if baseline else 0,
            cache_hit=baseline.cache_hit if baseline else False,
            source_versions={
                **(baseline.source_versions if baseline else {}),
                "code-health-policy": facts.policy_revision,
                "code-health-analyzer": CODE_HEALTH_ANALYZER_VERSION,
                "sonarqube": "normalized-web-api" if facts.sonar else "unavailable",
                "git-sizer": "json-v2" if facts.git_structure else "unavailable",
            },
            # Ineligible local components were removed and their weights were
            # renormalized above; exposing the full normalized denominator keeps
            # the shared composer from applying the same penalty a second time.
            available_weight=total_weight,
            total_weight=total_weight,
            raw_payload_ref=f"code-health://{facts.source_snapshot_digest}" if facts.source_snapshot_digest else None,
            diagnostics={
                **(baseline.diagnostics if baseline else {}),
                "code_health": facts.summary(),
                "code_health_components": {
                    name: {"score": value, "weight": resolved.component_weights.get(name), "eligible": value is not None}
                    for name, value in sorted(components.items())
                },
                "code_health_score_before": baseline.score if baseline else None,
                "code_health_score_after": final_score,
                "code_health_raw_score": raw_score,
                "code_health_eligible_weight": eligible_weight,
                "code_health_total_weight": total_weight,
                "double_counting_guard": "observation_metrics_only_aggregate_score",
            },
        )
        log.info(
            "code_health_analyzed",
            repo_id=context.repo_id,
            status=facts.status.value,
            score=final_score,
            confidence=facts.confidence,
            eligible_weight=eligible_weight,
        )
        return result

    @staticmethod
    def _has_usable_facts(facts: CodeHealthFacts) -> bool:
        return any(
            status in {CodeHealthStatus.MEASURED, CodeHealthStatus.PARTIAL}
            for status in facts.engine_statuses.values()
        )

    def _components(self, facts: CodeHealthFacts, policy: CodeHealthPolicy) -> dict[str, float | None]:
        sonar = facts.sonar
        todo = facts.todo_debt
        git = facts.git_structure
        ncloc = _number(_metric(sonar, "ncloc")) or 0.0
        rating = _rating_score(_metric(sonar, "maintainability_rating"), policy)
        debt_minutes = _number(_metric(sonar, "technical_debt_minutes"))
        debt_score = _inverse((debt_minutes / (ncloc / 1000.0)) if debt_minutes is not None and ncloc else debt_minutes, 0.0, 300.0)
        smells = _number(_metric(sonar, "code_smells"))
        smell_score = _inverse((smells / (ncloc / 1000.0)) if smells is not None and ncloc else smells, 0.0, 50.0)
        maintenance_values = [value for value in (rating, debt_score, smell_score) if value is not None]
        maintainability = sum(maintenance_values) / len(maintenance_values) if maintenance_values else None

        cognitive = _number(_metric(sonar, "cognitive_complexity"))
        cyclomatic = _number(_metric(sonar, "cyclomatic_complexity"))
        complexity_values = [
            _inverse((cognitive / (ncloc / 1000.0)) if cognitive is not None and ncloc else cognitive, 0.0, 50.0),
            _inverse((cyclomatic / (ncloc / 1000.0)) if cyclomatic is not None and ncloc else cyclomatic, 0.0, 100.0),
        ]
        complexity_values = [value for value in complexity_values if value is not None]
        complexity = sum(complexity_values) / len(complexity_values) if complexity_values else None

        duplication = _number(_metric(sonar, "duplicated_lines_density"))
        if duplication is None:
            duplicated_lines = _number(_metric(sonar, "duplicated_lines"))
            duplication = (duplicated_lines / ncloc * 100.0) if duplicated_lines is not None and ncloc else None
        duplication_score = _inverse(duplication, 0.0, 20.0)

        hotspot_score = None
        if todo and todo.status in {CodeHealthStatus.MEASURED, CodeHealthStatus.PARTIAL} and todo.diagnostics.get("hotspot_available"):
            ratio = todo.hotspot_count / max(1, todo.source_files)
            hotspot_score = max(0.0, 100.0 - min(100.0, ratio * 100.0))

        todo_score = None
        if todo and todo.status in {CodeHealthStatus.MEASURED, CodeHealthStatus.PARTIAL}:
            density_score = _inverse(todo.density_per_kloc, 0.0, 50.0)
            age_score = (100.0 - min(100.0, (todo.old_ratio or 0.0) * 100.0)) if todo.old_ratio is not None else None
            values = [value for value in (density_score, age_score) if value is not None]
            todo_score = sum(values) / len(values) if values else None

        git_score = None
        if git and git.status in {CodeHealthStatus.MEASURED, CodeHealthStatus.PARTIAL} and git.metrics:
            concerns = [_concern_score(value) for value in git.level_of_concern.values()]
            blob = _number(git.metrics.get("max_blob_size"))
            path_depth = _number(git.metrics.get("max_path_depth"))
            if blob is not None:
                concerns.append(_inverse(blob, 0.0, 1_000_000.0) or 0.0)
            if path_depth is not None:
                concerns.append(_inverse(path_depth, 0.0, 20.0) or 0.0)
            git_score = sum(concerns) / len(concerns) if concerns else 100.0
        return {
            "maintainability_debt": maintainability,
            "complexity": complexity,
            "duplication": duplication_score,
            "hotspots_churn": hotspot_score,
            "todo_debt": todo_score,
            "git_structure": git_score,
        }

    def _evidence_and_findings(self, context: AnalyzerContext, facts: CodeHealthFacts) -> tuple[list[EvidenceRef], list[Finding]]:
        evidence: list[EvidenceRef] = []
        findings: list[Finding] = []
        if facts.sonar:
            for index, item in enumerate(facts.sonar.issues):
                ref = _evidence(context, source="sonarqube", path=item.path, line=item.line, pointer=f"/issues/{index}", confidence=facts.sonar.confidence)
                evidence.append(ref)
                findings.append(
                    Finding(
                        id=f"repowise.health:sonarqube:{item.issue_id}",
                        analyzer_id="repowise.health",
                        subject=item.path or item.component or item.issue_id,
                        dimension="maintainability" if item.issue_type == "CODE_SMELL" else "defect",
                        severity=_severity(item.severity),
                        confidence=facts.sonar.confidence,
                        reason=item.message or item.rule or item.issue_type,
                        evidence_refs=(ref,),
                        location=FindingLocation(path=item.path, line_start=item.line, line_end=item.line, json_pointer=f"/issues/{index}"),
                        remediation="Review the SonarQube rule and apply the smallest safe fix.",
                        raw_impact=item.effort_minutes,
                        applied_impact=item.effort_minutes,
                    )
                )
        if facts.todo_debt:
            for item in facts.todo_debt.facts:
                old_todo_days = _number(facts.todo_debt.diagnostics.get("old_todo_days")) if facts.todo_debt else 180.0
                if item.age_days is None or item.age_days < (old_todo_days or 180.0):
                    continue
                ref = _evidence(context, source="git-history", path=item.path, line=item.line, confidence=facts.todo_debt.confidence)
                evidence.append(ref)
                findings.append(
                    Finding(
                        id=f"repowise.health:todo:{item.marker}:{item.path}:{item.line}",
                        analyzer_id="repowise.health",
                        subject=item.path,
                        dimension="maintainability",
                        severity="low",
                        confidence=facts.todo_debt.confidence,
                        reason=f"Old {item.marker} debt ({item.age_days:.0f} days)",
                        evidence_refs=(ref,),
                        location=FindingLocation(path=item.path, line_start=item.line, line_end=item.line),
                        remediation="Resolve, document, or remove the stale marker.",
                        raw_impact=item.age_days,
                        applied_impact=item.age_days,
                    )
                )
        if facts.git_structure:
            for _index, item in enumerate(facts.git_structure.evidence):
                evidence.append(_evidence(context, source="git-sizer", path=item.path or item.subject, pointer=item.json_pointer, confidence=facts.git_structure.confidence, tool_version="json-v2"))
        return evidence, findings

    def _fallback(self, context: AnalyzerContext, facts: CodeHealthFacts, baseline: AnalyzerResult | None) -> AnalyzerResult:
        if baseline is not None:
            diagnostics = {
                **baseline.diagnostics,
                "code_health": facts.summary(),
                "code_health_score_before": baseline.score,
                "code_health_score_after": baseline.score,
                "code_health_fallback": "baseline_preserved_optional_engine_unavailable",
                "double_counting_guard": "baseline_unchanged_no_usable_supplemental_facts",
            }
            return baseline.model_copy(update={"diagnostics": diagnostics})
        status = AnalyzerStatus.ERROR if facts.status is CodeHealthStatus.ERROR else AnalyzerStatus.SKIPPED
        return AnalyzerResult(
            analyzer_id="repowise.health",
            analyzer_version=CODE_HEALTH_ANALYZER_VERSION,
            status=status,
            score=None,
            score_dimension="code",
            limitations=(Limitation(reason="No usable Code Health engine or baseline was available", kind="missing_capability"),),
            diagnostics={"code_health": facts.summary(), "code_health_fallback": "no_usable_measurement"},
        )

    @staticmethod
    def _public_status(facts: CodeHealthFacts, score: float, findings: list[Finding], baseline: AnalyzerResult | None) -> AnalyzerStatus:
        if facts.status is CodeHealthStatus.ERROR and baseline is None:
            return AnalyzerStatus.ERROR
        if facts.status in {CodeHealthStatus.PARTIAL, CodeHealthStatus.UNAVAILABLE}:
            return AnalyzerStatus.WARN if baseline is None or baseline.status is not AnalyzerStatus.FAIL else AnalyzerStatus.FAIL
        if baseline and baseline.status is AnalyzerStatus.FAIL:
            return AnalyzerStatus.FAIL
        if score < 40.0 or any(item.severity == "critical" for item in findings):
            return AnalyzerStatus.FAIL
        if score < 75.0 or findings:
            return AnalyzerStatus.WARN
        return AnalyzerStatus.PASS


__all__ = ["CODE_HEALTH_ANALYZER_VERSION", "CodeHealthAnalyzer"]
