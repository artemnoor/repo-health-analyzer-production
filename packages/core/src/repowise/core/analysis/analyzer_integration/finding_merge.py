"""Deterministic cross-analyzer finding merge."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable

import structlog

from .contracts import AnalyzerResult, Finding

_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
log = structlog.get_logger(__name__)


def _identity(finding: Finding) -> str:
    """Return the legacy identity without normalizing internal whitespace."""
    location = finding.location
    payload = "|".join(
        (
            finding.dimension.casefold(),
            finding.subject.casefold(),
            (location.path if location and location.path else "").casefold(),
            str(location.line_start if location else ""),
            str(location.line_end if location else ""),
            " ".join(finding.reason.casefold().split()),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def finding_identity(finding: Finding) -> str:
    return _identity(finding)


def _merge_findings(owner: Finding, duplicate: Finding) -> Finding:
    refs = {ref.model_dump_json(): ref for ref in (*owner.evidence_refs, *duplicate.evidence_refs)}
    severity = max(
        (owner.severity, duplicate.severity), key=lambda value: _SEVERITY_RANK.get(value, 0)
    )
    return owner.model_copy(
        update={
            "evidence_refs": tuple(refs.values()),
            "remediation": owner.remediation or duplicate.remediation,
            "severity": severity,
            "confidence": max(owner.confidence, duplicate.confidence),
            "raw_impact": max(owner.raw_impact or 0.0, duplicate.raw_impact or 0.0) or None,
            "applied_impact": max(owner.applied_impact or 0.0, duplicate.applied_impact or 0.0)
            or None,
        }
    )


def deduplicate_findings(results: Iterable[AnalyzerResult]) -> tuple[AnalyzerResult, ...]:
    materialized = tuple(results)
    started = time.perf_counter()
    finding_count = sum(len(result.findings) for result in materialized)
    log.debug(
        "findings_merge_started",
        run_key=None,
        repository_id=None,
        repo_id=None,
        phase="merge",
        completed_phases=(),
        status="running",
        duration_ms=0,
        failure_kind=None,
        result_count=len(materialized),
        finding_count=finding_count,
    )
    owners: dict[str, tuple[int, Finding]] = {}
    merged: dict[int, list[Finding]] = {index: [] for index in range(len(materialized))}
    for index, result in enumerate(materialized):
        for finding in result.findings:
            key = finding_identity(finding)
            current = owners.get(key)
            if current is None:
                owners[key] = (index, finding)
                merged[index].append(finding)
                continue
            owner_index, owner = current
            updated = _merge_findings(owner, finding)
            owners[key] = (owner_index, updated)
            merged[owner_index] = [
                updated if item.id == owner.id else item for item in merged[owner_index]
            ]
    output = tuple(
        result.model_copy(update={"findings": tuple(merged[index])})
        for index, result in enumerate(materialized)
    )
    log.info(
        "findings_merge_finished",
        run_key=None,
        repository_id=None,
        repo_id=None,
        phase="merge",
        completed_phases=(),
        status="completed",
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        failure_kind=None,
        result_count=len(output),
        finding_count=sum(len(result.findings) for result in output),
        merged_count=finding_count - sum(len(result.findings) for result in output),
    )
    return output


__all__ = ["deduplicate_findings", "finding_identity"]
