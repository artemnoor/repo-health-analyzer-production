"""Stable cross-analyzer finding merge with provenance preservation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .contracts import AnalyzerResult, Finding

_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _identity(finding: Finding) -> str:
    location = finding.location
    payload = "|".join(
        (
            finding.dimension.casefold(),
            finding.subject.casefold(),
            (location.path if location else "").casefold(),
            str(location.line_start if location else ""),
            str(location.line_end if location else ""),
            " ".join(finding.reason.casefold().split()),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def deduplicate_findings(results: Iterable[AnalyzerResult]) -> tuple[AnalyzerResult, ...]:
    """Merge equivalent observations while retaining all source evidence."""
    materialized = tuple(results)
    owners: dict[str, tuple[int, Finding]] = {}
    merged: dict[int, list[Finding]] = {index: [] for index in range(len(materialized))}
    for index, result in enumerate(materialized):
        for finding in result.findings:
            key = _identity(finding)
            current = owners.get(key)
            if current is None:
                owners[key] = (index, finding)
                merged[index].append(finding)
                continue
            owner_index, owner = current
            refs = {ref.model_dump_json(): ref for ref in (*owner.evidence_refs, *finding.evidence_refs)}
            remediation = owner.remediation or finding.remediation
            severity = max((owner.severity, finding.severity), key=lambda value: _SEVERITY_RANK.get(value, 0))
            updated = owner.model_copy(
                update={
                    "evidence_refs": tuple(refs.values()),
                    "remediation": remediation,
                    "severity": severity,
                    "confidence": max(owner.confidence, finding.confidence),
                    "raw_impact": max(owner.raw_impact or 0.0, finding.raw_impact or 0.0) or None,
                    "applied_impact": max(owner.applied_impact or 0.0, finding.applied_impact or 0.0) or None,
                }
            )
            owners[key] = (owner_index, updated)
            merged[owner_index] = [updated if item.id == owner.id else item for item in merged[owner_index]]
    return tuple(
        result.model_copy(update={"findings": tuple(merged[index])})
        for index, result in enumerate(materialized)
    )


__all__ = ["deduplicate_findings"]
