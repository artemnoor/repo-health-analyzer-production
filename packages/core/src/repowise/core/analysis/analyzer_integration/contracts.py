"""Versioned, product-neutral analyzer contracts.

The models in this module intentionally contain normalized observations only.
Product scoring, persistence records, and public projections are supplied by
the health edge through :mod:`ports`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnalyzerStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED = "skipped"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class CachePolicy(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"

    @property
    def can_read(self) -> bool:
        return self in {self.READ, self.READ_WRITE}

    @property
    def can_write(self) -> bool:
        return self in {self.WRITE, self.READ_WRITE}


def _stable_names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    items = cast(Iterable[object], value)
    return tuple(sorted({str(item).strip() for item in items if str(item).strip()}))


class AnalyzerDefinition(ContractModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    category: str = Field(min_length=1)
    dimensions: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()
    phase: int = Field(default=100, ge=0)
    cost: int = Field(default=100, ge=0)
    timeout: float = Field(default=60.0, gt=0)
    cache_policy: CachePolicy = CachePolicy.READ_WRITE
    source_commit: str | None = None
    experimental: bool = False
    enabled_by_mode: tuple[str, ...] = ()

    @field_validator("dimensions", "requires", "supports", "enabled_by_mode", mode="before")
    @classmethod
    def _stable_names(cls, value: object) -> tuple[str, ...]:
        return _stable_names(value)


class AnalyzerContext(ContractModel):
    repo_path: Path
    repo_id: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    as_of_ts: datetime
    scope: str = "all"
    mode: str = "fast"
    inventory: dict[str, Any] = Field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    tool_paths: dict[str, str] = Field(default_factory=dict)
    config_digest: str | None = None
    time_budget: float | None = Field(default=None, ge=0)
    cache_dir: Path | None = None

    @field_validator("capabilities", mode="before")
    @classmethod
    def _stable_capabilities(cls, value: object) -> tuple[str, ...]:
        return _stable_names(value)


class EvidenceRef(ContractModel):
    source: str = Field(min_length=1)
    source_commit: str | None = None
    tool_version: str | None = None
    path: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    json_pointer: str | None = None
    snippet_hash: str | None = None
    collected_at: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    redaction: Literal["none", "partial", "full"] = "none"

    @model_validator(mode="after")
    def _valid_line_range(self) -> EvidenceRef:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class Limitation(ContractModel):
    reason: str = Field(min_length=1)
    kind: Literal[
        "missing_capability",
        "insufficient_denominator",
        "unsupported",
        "remediation_unavailable",
        "stale",
        "timeout",
        "error",
        "other",
    ] = "other"
    affected_scope: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()


class MetricValue(ContractModel):
    name: str = Field(min_length=1)
    dimension: str | None = None
    value: float | int | str | bool | None = None
    unit: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    population: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    evidence_refs: tuple[EvidenceRef, ...] = ()


Metric = MetricValue


class FindingLocation(ContractModel):
    path: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    symbol: str | None = None
    json_pointer: str | None = None

    @model_validator(mode="after")
    def _valid_line_range(self) -> FindingLocation:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class Finding(ContractModel):
    id: str = Field(min_length=1)
    analyzer_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    evidence_refs: tuple[EvidenceRef, ...] = ()
    location: FindingLocation | None = None
    remediation: str | None = None
    raw_impact: float | None = None
    applied_impact: float | None = None


class AnalyzerResult(ContractModel):
    schema_version: Literal[1] = 1
    analyzer_id: str = Field(min_length=1)
    analyzer_version: str = Field(min_length=1)
    status: AnalyzerStatus
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    score_dimension: str | None = None
    metrics: tuple[MetricValue, ...] = ()
    findings: tuple[Finding, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    limitations: tuple[Limitation, ...] = ()
    duration_ms: int = Field(default=0, ge=0)
    cache_hit: bool = False
    source_versions: dict[str, str] = Field(default_factory=dict)
    available_weight: float = Field(default=0.0, ge=0.0)
    total_weight: float = Field(default=0.0, ge=0.0)
    raw_payload_ref: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_score_and_weights(self) -> AnalyzerResult:
        if self.status in {AnalyzerStatus.SKIPPED, AnalyzerStatus.ERROR} and self.score is not None:
            raise ValueError(f"score must be absent when status is {self.status.value}")
        if self.available_weight > self.total_weight:
            raise ValueError("available_weight cannot exceed total_weight")
        return self

    @classmethod
    def skipped(
        cls,
        definition: AnalyzerDefinition,
        reason: str,
        *,
        kind: Literal["missing_capability", "unsupported", "stale", "other"] = "missing_capability",
    ) -> AnalyzerResult:
        return cls(
            analyzer_id=definition.id,
            analyzer_version=definition.version,
            status=AnalyzerStatus.SKIPPED,
            limitations=(Limitation(reason=reason, kind=kind),),
        )

    @classmethod
    def insufficient_denominator(
        cls,
        definition: AnalyzerDefinition,
        reason: str,
        *,
        total_weight: float = 0.0,
    ) -> AnalyzerResult:
        return cls(
            analyzer_id=definition.id,
            analyzer_version=definition.version,
            status=AnalyzerStatus.INCONCLUSIVE,
            total_weight=total_weight,
            limitations=(Limitation(reason=reason, kind="insufficient_denominator"),),
        )


__all__ = [
    "AnalyzerContext",
    "AnalyzerDefinition",
    "AnalyzerResult",
    "AnalyzerStatus",
    "CachePolicy",
    "ContractModel",
    "EvidenceRef",
    "Finding",
    "FindingLocation",
    "Limitation",
    "Metric",
    "MetricValue",
]
