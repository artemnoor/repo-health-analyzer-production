"""Compatibility adapters from the legacy neutral analyzer contracts.

The imports here are intentionally one-way: legacy callers may be adapted to
the new Repo Health boundary, while new contracts never import an analyzer,
API, persistence, or provider implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
)
from repowise.core.analysis.analyzer_integration.contracts import (
    Finding as LegacyFinding,
)
from repowise.core.analysis.analyzer_integration.contracts import (
    FindingLocation as LegacyFindingLocation,
)
from repowise.core.analysis.analyzer_integration.contracts import (
    Limitation as LegacyLimitation,
)
from repowise.core.analysis.analyzer_integration.contracts import (
    MetricValue as LegacyMetricValue,
)

from .requests import RepositoryRef, canonical_json
from .results import (
    AnalyzerInput,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    Evidence,
    Finding,
    FindingLocation,
    HealthCategory,
    Limitation,
    Metric,
    RepositoryFacts,
)

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)
_CATEGORY_BY_ANALYZER_ID = {
    "vale.documentation": HealthCategory.DOCUMENTATION,
    "chaoss.activity": HealthCategory.ACTIVITY,
    "chaoss.issues_prs": HealthCategory.ISSUES,
    "cicd.sourcecraft": HealthCategory.CICD,
    "sourcecraft.appsec": HealthCategory.SECURITY,
    "repowise.health": HealthCategory.CODE_HEALTH,
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _relative_path(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().replace("\\", "/")
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or normalized.startswith(("../", "./"))
        or "/../" in f"/{normalized}/"
    ):
        return None
    return normalized


def _safe_digest(value: Any) -> str:
    try:
        encoded = canonical_json(value)
    except (TypeError, ValueError):
        encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _evidence_id(reference: EvidenceRef) -> str:
    payload = reference.model_dump(mode="json")
    return f"evidence-{_safe_digest(payload)[:24]}"


def _adapt_evidence(reference: EvidenceRef) -> Evidence:
    path = _relative_path(reference.path)
    redaction = reference.redaction
    if reference.path and path is None:
        redaction = "partial"
    return Evidence(
        evidence_id=_evidence_id(reference),
        source=reference.source,
        source_version=reference.tool_version or reference.source_commit,
        relative_path=path,
        line_start=reference.line_start,
        line_end=reference.line_end,
        json_pointer=reference.json_pointer,
        snippet_hash=reference.snippet_hash,
        collected_at=_utc(reference.collected_at),
        confidence=Confidence(
            value=reference.confidence, level="high" if reference.confidence >= 0.8 else "medium"
        ),
        redaction=redaction,
    )


def _adapt_location(location: Any) -> FindingLocation | None:
    if location is None:
        return None
    return FindingLocation(
        relative_path=_relative_path(location.path),
        line_start=location.line_start,
        line_end=location.line_end,
        symbol=location.symbol,
    )


def _adapt_finding(
    finding: LegacyFinding,
    *,
    category: HealthCategory,
    evidence_by_key: dict[str, Evidence],
) -> Finding:
    evidence_ids: list[str] = []
    for reference in finding.evidence_refs:
        key = _evidence_id(reference)
        evidence_by_key.setdefault(key, _adapt_evidence(reference))
        evidence_ids.append(key)
    return Finding(
        analyzer_id=finding.analyzer_id,
        subject=finding.subject,
        category=category,
        dimension=finding.dimension,
        severity=finding.severity,
        confidence=Confidence(
            value=finding.confidence,
            level="high"
            if finding.confidence >= 0.8
            else "medium"
            if finding.confidence >= 0.5
            else "low",
        ),
        reason=finding.reason,
        evidence_ids=evidence_ids,
        location=_adapt_location(finding.location),
        remediation=finding.remediation,
    )


def analyzer_context_to_input(
    context: AnalyzerContext,
    *,
    analysis_id: str,
    repository: RepositoryRef,
    facts: RepositoryFacts,
    analyzer_id: str,
    analyzer_version: str,
    policy_digest: str,
    deadline_at: datetime | None = None,
) -> AnalyzerInput:
    """Adapt a legacy context without serializing its checkout path.

    ``repository`` is explicit because a local checkout path cannot be
    promoted to a canonical provider URI by inference.
    """

    if context.repo_id != repository.repository_id:
        raise ValueError("legacy context and RepositoryRef identify different repositories")
    if (
        repository.head_sha
        and _SHA_RE.fullmatch(context.head_sha)
        and repository.head_sha.lower() != context.head_sha.lower()
    ):
        raise ValueError("legacy context and RepositoryRef identify different commits")
    return AnalyzerInput(
        analysis_id=analysis_id,
        repository=repository,
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest=policy_digest,
        deadline_at=deadline_at,
    )


def analyzer_result_to_category_result(
    result: AnalyzerResult,
    *,
    analysis_id: str,
    category: HealthCategory | None = None,
    confidence: Confidence | None = None,
    analyzer_id: str | None = None,
) -> CategoryResult:
    """Adapt legacy result values while redacting absolute locations."""

    resolved_category = category or _CATEGORY_BY_ANALYZER_ID.get(result.analyzer_id)
    if resolved_category is None:
        raise ValueError(f"category is required for unknown analyzer: {result.analyzer_id}")
    evidence_by_key: dict[str, Evidence] = {}
    for reference in result.evidence:
        adapted = _adapt_evidence(reference)
        evidence_by_key[adapted.evidence_id] = adapted
    metrics = []
    for item in result.metrics:
        metric_evidence_ids = []
        for reference in item.evidence_refs:
            adapted = _adapt_evidence(reference)
            evidence_by_key.setdefault(adapted.evidence_id, adapted)
            metric_evidence_ids.append(adapted.evidence_id)
        metrics.append(
            Metric(
                name=item.name,
                value=item.value,
                unit=item.unit,
                score=item.score,
                evidence_ids=metric_evidence_ids,
            )
        )
    findings = tuple(
        _adapt_finding(item, category=resolved_category, evidence_by_key=evidence_by_key)
        for item in result.findings
    )
    evidence = tuple(evidence_by_key.values())
    status = CategoryStatus(result.status.value)
    if result.total_weight > 0:
        coverage_status = (
            "available" if result.available_weight >= result.total_weight else "partial"
        )
    else:
        coverage_status = "unavailable"
    result_confidence = confidence or Confidence(
        value=0.0 if status in {CategoryStatus.SKIPPED, CategoryStatus.ERROR} else 1.0,
        level="unknown" if status in {CategoryStatus.SKIPPED, CategoryStatus.ERROR} else "high",
    )
    score_signals = {
        key: int(value)
        for key, value in result.diagnostics.items()
        if key
        in {
            "active_findings",
            "active_finding_count",
            "critical_findings",
            "high_findings",
            "confirmed_secret_count",
            "secret_findings",
        }
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= int(value) <= 1_000_000
    }
    if "active_finding_count" in score_signals:
        score_signals["active_findings"] = score_signals.pop("active_finding_count")
    limitations = tuple(
        Limitation(code=item.kind, reason=item.reason, affected_scope=item.affected_scope)
        for item in result.limitations
    )
    return CategoryResult(
        analysis_id=analysis_id,
        analyzer_id=analyzer_id or result.analyzer_id,
        analyzer_version=result.analyzer_version,
        category=resolved_category,
        status=status,
        score=result.score,
        metrics=tuple(metrics),
        findings=findings,
        evidence=evidence,
        coverage=Coverage(
            status=coverage_status,
            covered=round(result.available_weight * 1000),
            total=round(result.total_weight * 1000),
            covered_weight=result.available_weight if result.total_weight > 0 else None,
            total_weight=result.total_weight if result.total_weight > 0 else None,
        ),
        confidence=result_confidence,
        limitations=limitations,
        diagnostics_digest=_safe_digest(result.diagnostics) if result.diagnostics else None,
        score_signals=score_signals,
        source_versions=result.source_versions,
    )


_CANONICAL_TO_LEGACY_ANALYZER_ID = {
    "repo-health.documentation": "vale.documentation",
    "repo-health.activity": "chaoss.activity",
    "repo-health.issues": "chaoss.issues_prs",
    "repo-health.cicd": "cicd.sourcecraft",
    "repo-health.security": "sourcecraft.appsec",
    "repo-health.code-health": "repowise.health",
}
_LEGACY_LIMITATION_KINDS = {
    "missing_capability",
    "insufficient_denominator",
    "unsupported",
    "remediation_unavailable",
    "stale",
    "timeout",
    "error",
    "other",
}


def category_result_to_analyzer_result(result: CategoryResult) -> AnalyzerResult:
    """Decode a canonical category for the frozen v1 engine only.

    This is a compatibility projection, not a second score path. The v1
    engine remains the sole owner of weighting, K, and security-cap arithmetic.
    """

    evidence_by_id = {
        item.evidence_id: EvidenceRef(
            source=item.source,
            source_commit=item.source_version,
            tool_version=item.source_version,
            path=item.relative_path,
            line_start=item.line_start,
            line_end=item.line_end,
            json_pointer=item.json_pointer,
            snippet_hash=item.snippet_hash or item.content_hash,
            collected_at=item.collected_at,
            confidence=item.confidence.value,
            redaction=item.redaction,
        )
        for item in result.evidence
    }
    legacy_analyzer_id = _CANONICAL_TO_LEGACY_ANALYZER_ID.get(result.analyzer_id, result.analyzer_id)
    legacy_findings = tuple(
        LegacyFinding(
            id=item.finding_id or "finding-unknown",
            analyzer_id=legacy_analyzer_id,
            subject=item.subject or item.dimension,
            dimension=item.dimension,
            severity=item.severity,
            confidence=item.confidence.value,
            reason=item.reason,
            evidence_refs=tuple(
                evidence_by_id[evidence_id]
                for evidence_id in item.evidence_ids
                if evidence_id in evidence_by_id
            ),
            location=(
                LegacyFindingLocation(
                    path=item.location.relative_path,
                    line_start=item.location.line_start,
                    line_end=item.location.line_end,
                    symbol=item.location.symbol,
                )
                if item.location
                else None
            ),
            remediation=item.remediation,
        )
        for item in result.findings
    )
    total_weight = result.coverage.total_weight or (1.0 if result.coverage.total > 0 else 0.0)
    available_weight = result.coverage.covered_weight
    if available_weight is None:
        available_weight = (
            total_weight * result.coverage.covered / result.coverage.total
            if result.coverage.total > 0
            else 0.0
        )
    limitations = tuple(
        LegacyLimitation(
            reason=item.reason,
            kind=item.code if item.code in _LEGACY_LIMITATION_KINDS else "other",
            affected_scope=item.affected_scope,
            evidence_refs=(),
        )
        for item in result.limitations
    )
    status = AnalyzerStatus(result.status.value)
    coverage = (
        result.coverage.covered_weight / result.coverage.total_weight
        if result.coverage.covered_weight is not None and result.coverage.total_weight
        else (result.coverage.covered / result.coverage.total if result.coverage.total else 0.0)
    )
    return AnalyzerResult(
        analyzer_id=legacy_analyzer_id,
        analyzer_version=result.analyzer_version,
        status=status,
        score=result.score,
        score_dimension=result.category.value,
        metrics=tuple(
            LegacyMetricValue(
                name=item.name,
                value=item.value,
                unit=item.unit,
                score=item.score,
                evidence_refs=tuple(
                    evidence_by_id[evidence_id]
                    for evidence_id in item.evidence_ids
                    if evidence_id in evidence_by_id
                ),
            )
            for item in result.metrics
        ),
        findings=legacy_findings,
        evidence=tuple(evidence_by_id.values()),
        limitations=limitations,
        source_versions=result.source_versions,
        available_weight=available_weight,
        total_weight=total_weight,
        diagnostics={
            "category_status": "MEASURED"
            if result.status in {CategoryStatus.PASS, CategoryStatus.WARN, CategoryStatus.FAIL}
            else result.status.value.upper(),
            "coverage": coverage,
            "confidence": result.confidence.value,
            **result.score_signals,
        },
    )


__all__ = [
    "analyzer_context_to_input",
    "analyzer_result_to_category_result",
    "category_result_to_analyzer_result",
]
