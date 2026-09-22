"""Transport-neutral facts, analyzer, score, and result contracts.

The models in this module are deliberately independent from the current
analyzer implementations.  They can be encoded as JSON and handed to a
local callable, a subprocess, or a queue worker without importing the API,
database, or an external provider SDK.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .requests import (
    CONTRACT_SCHEMA_VERSION,
    AnalysisRequest,
    AssessmentProfile,
    RepositoryRef,
    canonical_json,
    contract_digest,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{8,128}$")
_SECRET_MARKERS = ("api_key", "apikey", "bearer ", "password", "secret", "token")


class _ContractBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_schema_version(cls, value: object) -> object:
        if isinstance(value, Mapping):
            version = value.get("schema_version", CONTRACT_SCHEMA_VERSION)
            if version != CONTRACT_SCHEMA_VERSION:
                # Reuse the explicit request-contract error type without
                # coupling result consumers to an executor implementation.
                from .requests import UnsupportedContractVersion

                raise UnsupportedContractVersion(version, contract=cls.__name__)
        return value

    def to_json(self) -> str:
        return canonical_json(self)

    def digest(self) -> str:
        return contract_digest(self)


def _normalize_id(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a bounded stable identifier")
    if any(marker in normalized.lower() for marker in _SECRET_MARKERS):
        raise ValueError(f"{field_name} must not contain secret-like material")
    return normalized


def _normalize_key(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip().lower()
    if not _KEY_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a bounded lowercase key")
    return normalized


def _normalize_digest(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a hexadecimal digest")
    normalized = value.strip().lower()
    if not _DIGEST_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be 8-128 hexadecimal characters")
    return normalized


def _normalize_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be an aware UTC timestamp")
    return value.astimezone(UTC)


def _normalize_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("path must be a relative repository path")
    normalized = value.strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or normalized.startswith(("../", "./"))
        or "/../" in f"/{normalized}/"
        or "\x00" in normalized
    ):
        raise ValueError("path must be relative and must not escape the repository")
    return normalized


def _stable_ids(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{field_name} must be an iterable of IDs") from exc
    return tuple(sorted({_normalize_id(item, field_name=field_name) for item in values}))


class HealthCategory(StrEnum):
    DOCUMENTATION = "documentation"
    ACTIVITY = "activity"
    ISSUES = "issues"
    CICD = "cicd"
    SECURITY = "security"
    CODE_HEALTH = "code_health"


class CategoryStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED = "skipped"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class AnalysisState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CollectionState(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    ERROR = "error"


class ProviderCapabilityState(StrEnum):
    """Safe capability state carried with an assessment snapshot."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"


class AppSecScanState(StrEnum):
    """Lifecycle state of the selected SourceCraft AppSec scan."""

    NO_SCAN = "no_scan"
    FINISHED_ZERO_FINDINGS = "finished_zero_findings"
    FINISHED_WITH_FINDINGS = "finished_with_findings"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"


class Confidence(_ContractBase):
    """Confidence is explicit so missing evidence is not confused with zero."""

    value: float = Field(ge=0.0, le=1.0)
    level: Literal["unknown", "low", "medium", "high"] = "unknown"
    reason: str | None = Field(default=None, max_length=512)


class Coverage(_ContractBase):
    """Coverage denominator and availability are first-class values."""

    status: Literal["unavailable", "partial", "available", "complete"]
    covered: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    covered_weight: float | None = Field(default=None, ge=0.0)
    total_weight: float | None = Field(default=None, gt=0.0)
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _valid_denominator(self) -> Coverage:
        if self.covered > self.total:
            raise ValueError("coverage covered cannot exceed total")
        if self.total == 0 and self.status not in {"unavailable", "partial"}:
            raise ValueError("available coverage requires a positive denominator")
        if self.covered_weight is not None and self.total_weight is None:
            raise ValueError("covered_weight requires total_weight")
        if (
            self.covered_weight is not None
            and self.total_weight is not None
            and self.covered_weight > self.total_weight
        ):
            raise ValueError("coverage covered_weight cannot exceed total_weight")
        return self


class Evidence(_ContractBase):
    """Redacted provenance reference; raw provider payloads are not accepted."""

    evidence_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=256)
    source_version: str | None = Field(default=None, max_length=128)
    relative_path: str | None = Field(default=None, max_length=4096)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    json_pointer: str | None = Field(default=None, max_length=1024)
    content_hash: str | None = Field(default=None, max_length=128)
    snippet_hash: str | None = Field(default=None, max_length=128)
    collected_at: datetime
    confidence: Confidence = Field(default_factory=lambda: Confidence(value=1.0, level="high"))
    redaction: Literal["none", "partial", "full"] = "none"

    _evidence_id = field_validator("evidence_id", mode="before")(
        lambda value: _normalize_id(value, field_name="evidence_id")
    )
    _relative_path = field_validator("relative_path", mode="before")(
        lambda value: None if value is None else _normalize_relative_path(value)
    )
    _content_hash = field_validator("content_hash", "snippet_hash", mode="before")(
        lambda value, info: None if value is None else _normalize_digest(value, field_name=info.field_name)
    )
    _collected_at = field_validator("collected_at", mode="after")(
        lambda value: _normalize_utc(value, field_name="collected_at")
    )

    @model_validator(mode="after")
    def _valid_location(self) -> Evidence:
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_end requires line_start")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        if self.json_pointer is not None and not self.json_pointer.startswith("/"):
            raise ValueError("json_pointer must be an RFC 6901-style relative pointer")
        return self


class FindingLocation(_ContractBase):
    """Location is always relative to the analyzed repository snapshot."""

    relative_path: str | None = Field(default=None, max_length=4096)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    symbol: str | None = Field(default=None, max_length=512)

    _relative_path = field_validator("relative_path", mode="before")(
        lambda value: None if value is None else _normalize_relative_path(value)
    )

    @model_validator(mode="after")
    def _valid_line_range(self) -> FindingLocation:
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_end requires line_start")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class Finding(_ContractBase):
    """Stable, actionable analyzer finding with redacted evidence links."""

    finding_id: str | None = Field(default=None, max_length=128)
    analyzer_id: str = Field(min_length=1, max_length=128)
    subject: str | None = Field(default=None, max_length=512)
    category: HealthCategory
    dimension: str = Field(min_length=1, max_length=128)
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: Confidence
    reason: str = Field(min_length=1, max_length=2000)
    location: FindingLocation | None = None
    remediation: str | None = Field(default=None, max_length=2000)
    evidence_ids: tuple[str, ...] = ()

    _analyzer_id = field_validator("analyzer_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analyzer_id")
    )
    _dimension = field_validator("dimension", mode="before")(
        lambda value: _normalize_key(value, field_name="dimension")
    )
    _evidence_ids = field_validator("evidence_ids", mode="before")(
        lambda value: _stable_ids(value, field_name="evidence_ids")
    )

    @model_validator(mode="after")
    def _derive_deterministic_id(self) -> Finding:
        if self.finding_id is None:
            payload = {
                "analyzer_id": self.analyzer_id,
                "category": self.category.value,
                "subject": self.subject,
                "dimension": self.dimension,
                "severity": self.severity,
                "reason": self.reason,
                "location": self.location.model_dump(mode="json") if self.location else None,
                "evidence_ids": self.evidence_ids,
            }
            object.__setattr__(
                self,
                "finding_id",
                f"finding-{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()[:24]}",
            )
        else:
            object.__setattr__(
                self,
                "finding_id",
                _normalize_id(self.finding_id, field_name="finding_id"),
            )
        return self


class Limitation(_ContractBase):
    code: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    affected_scope: str | None = Field(default=None, max_length=512)

    _code = field_validator("code", mode="before")(lambda value: _normalize_key(value, field_name="code"))


class SourceStatus(_ContractBase):
    """Provenance and capability state for one collection source."""

    source_id: str = Field(min_length=1, max_length=128)
    state: CollectionState
    source_version: str | None = Field(default=None, max_length=128)
    snapshot_digest: str | None = Field(default=None, max_length=128)
    collected_at: datetime | None = None
    limitations: tuple[Limitation, ...] = ()

    _source_id = field_validator("source_id", mode="before")(lambda value: _normalize_id(value, field_name="source_id"))
    _snapshot_digest = field_validator("snapshot_digest", mode="before")(
        lambda value: None if value is None else _normalize_digest(value, field_name="snapshot_digest")
    )
    _collected_at = field_validator("collected_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="collected_at")
    )

    @model_validator(mode="after")
    def _stable_limitations(self) -> SourceStatus:
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations, key=lambda item: item.code)))
        return self


class CapabilityStatus(_ContractBase):
    """Provider/tool capability metadata without credentials or payloads."""

    capability_id: str = Field(min_length=1, max_length=128)
    state: ProviderCapabilityState
    reason: str = Field(min_length=1, max_length=512)

    _capability_id = field_validator("capability_id", mode="before")(
        lambda value: _normalize_id(value, field_name="capability_id")
    )


class Metric(_ContractBase):
    name: str = Field(min_length=1, max_length=128)
    value: float | int | str | bool | None = None
    unit: str | None = Field(default=None, max_length=64)
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    evidence_ids: tuple[str, ...] = ()

    _name = field_validator("name", mode="before")(lambda value: _normalize_key(value, field_name="name"))
    _evidence_ids = field_validator("evidence_ids", mode="before")(
        lambda value: _stable_ids(value, field_name="evidence_ids")
    )


class FactObservation(_ContractBase):
    key: str = Field(min_length=1, max_length=128)
    value: bool | int | float | str | None = None
    unit: str | None = Field(default=None, max_length=64)
    evidence_ids: tuple[str, ...] = ()

    _key = field_validator("key", mode="before")(lambda value: _normalize_key(value, field_name="key"))
    _evidence_ids = field_validator("evidence_ids", mode="before")(
        lambda value: _stable_ids(value, field_name="evidence_ids")
    )

    @field_validator("value", mode="before")
    @classmethod
    def _reject_unredacted_values(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if len(normalized) > 512:
            raise ValueError("fact observation strings must be at most 512 characters")
        if any(marker in normalized.casefold() for marker in _SECRET_MARKERS):
            raise ValueError("fact observations must not contain secret-like material")
        if (
            normalized.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z]:[\\/]", normalized)
            or normalized.startswith(("../", "./"))
        ):
            raise ValueError("fact observations must not contain absolute or escaping paths")
        return normalized


class FactGroup(_ContractBase):
    available: bool = False
    observations: tuple[FactObservation, ...] = ()
    limitations: tuple[Limitation, ...] = ()

    @model_validator(mode="after")
    def _stable_observations(self) -> FactGroup:
        object.__setattr__(self, "observations", tuple(sorted(self.observations, key=lambda item: item.key)))
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations, key=lambda item: item.code)))
        return self


class GitFacts(FactGroup):
    pass


class DocumentationFacts(FactGroup):
    pass


class IssuesFacts(FactGroup):
    pass


class CicdFacts(FactGroup):
    pass


class SecurityFacts(FactGroup):
    scan_state: AppSecScanState | None = None


class CodeHealthFacts(FactGroup):
    pass


class RepositoryFacts(_ContractBase):
    """Normalized facts grouped by bounded context, never raw provider data."""

    repository: RepositoryRef | None = None
    assessment_profile: AssessmentProfile = AssessmentProfile.PUBLIC
    source_snapshot_digest: str | None = Field(default=None, max_length=128)
    collected_at: datetime | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
    source_statuses: tuple[SourceStatus, ...] = ()
    git: GitFacts = Field(default_factory=GitFacts)
    documentation: DocumentationFacts = Field(default_factory=DocumentationFacts)
    issues: IssuesFacts = Field(default_factory=IssuesFacts)
    cicd: CicdFacts = Field(default_factory=CicdFacts)
    security: SecurityFacts = Field(default_factory=SecurityFacts)
    code_health: CodeHealthFacts = Field(default_factory=CodeHealthFacts)
    capabilities: tuple[str, ...] = ()
    used_sources: tuple[str, ...] = ()
    capability_states: tuple[CapabilityStatus, ...] = ()
    limitations: tuple[Limitation, ...] = ()

    _capabilities = field_validator("capabilities", mode="before")(
        lambda value: _stable_ids(value, field_name="capabilities")
    )
    _used_sources = field_validator("used_sources", mode="before")(
        lambda value: _stable_ids(value, field_name="used_sources")
    )
    _source_snapshot_digest = field_validator("source_snapshot_digest", mode="before")(
        lambda value: None if value is None else _normalize_digest(value, field_name="source_snapshot_digest")
    )
    _collected_at = field_validator("collected_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="collected_at")
    )

    @field_validator("source_versions", mode="before")
    @classmethod
    def _bounded_source_versions(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("source_versions must be a mapping")
        result: dict[str, str] = {}
        for raw_key, raw_version in value.items():
            key = _normalize_id(raw_key, field_name="source_versions key")
            if not isinstance(raw_version, str) or not raw_version.strip():
                raise ValueError("source_versions values must be non-empty strings")
            version = raw_version.strip()
            if len(version) > 128 or any(marker in version.casefold() for marker in _SECRET_MARKERS):
                raise ValueError("source_versions must be bounded and secret-free")
            result[key] = version
        return result

    @model_validator(mode="after")
    def _stable_limitations(self) -> RepositoryFacts:
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations, key=lambda item: item.code)))
        object.__setattr__(
            self, "source_statuses", tuple(sorted(self.source_statuses, key=lambda item: item.source_id))
        )
        object.__setattr__(
            self,
            "capability_states",
            tuple(sorted(self.capability_states, key=lambda item: item.capability_id)),
        )
        return self

    def digest_payload(self) -> dict[str, Any]:
        """Return the redacted stable payload used for cache identity.

        Collection timestamps and self-referential source snapshot digests are
        provenance, not fact identity. They are intentionally excluded so a
        local and worker collection of the same snapshot share a cache key.
        """

        payload = self.model_dump(mode="json")
        payload.pop("collected_at", None)
        payload.pop("source_snapshot_digest", None)
        if self.assessment_profile is AssessmentProfile.PUBLIC and not self.used_sources and not self.capability_states:
            # Existing default/public facts keep their cache and evidence
            # identity.  Non-default context is intentionally part of the
            # digest so public and owner snapshots cannot collide.
            payload.pop("assessment_profile", None)
            payload.pop("used_sources", None)
            payload.pop("capability_states", None)
            if isinstance(payload.get("security"), dict) and self.security.scan_state is None:
                payload["security"].pop("scan_state", None)
        for status in payload.get("source_statuses", ()):
            status.pop("collected_at", None)
            status.pop("snapshot_digest", None)
        return payload

    def digest(self) -> str:
        return contract_digest(self.digest_payload())


class AnalyzerInput(_ContractBase):
    """Input an analyzer can consume without knowing the collector internals."""

    analysis_id: str = Field(min_length=1, max_length=128)
    as_of: datetime
    repository: RepositoryRef
    assessment_profile: AssessmentProfile = AssessmentProfile.PUBLIC
    analyzer_id: str = Field(min_length=1, max_length=128)
    analyzer_version: str = Field(min_length=1, max_length=128)
    facts: RepositoryFacts
    facts_digest: str = Field(min_length=8, max_length=128)
    policy_digest: str = Field(min_length=8, max_length=128)
    deadline_at: datetime | None = None

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analysis_id")
    )
    _analyzer_id = field_validator("analyzer_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analyzer_id")
    )
    _analyzer_version = field_validator("analyzer_version", mode="before")(
        lambda value: _normalize_id(value, field_name="analyzer_version")
    )
    _facts_digest = field_validator("facts_digest", mode="before")(
        lambda value: _normalize_digest(value, field_name="facts_digest")
    )
    _policy_digest = field_validator("policy_digest", mode="before")(
        lambda value: _normalize_digest(value, field_name="policy_digest")
    )
    _as_of = field_validator("as_of", mode="after")(lambda value: _normalize_utc(value, field_name="as_of"))
    _deadline_at = field_validator("deadline_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="deadline_at")
    )

    @model_validator(mode="after")
    def _facts_digest_matches(self) -> AnalyzerInput:
        if self.facts_digest != self.facts.digest():
            raise ValueError("facts_digest does not match normalized RepositoryFacts")
        if self.facts.assessment_profile is not self.assessment_profile:
            raise ValueError("AnalyzerInput profile must match RepositoryFacts")
        return self


class CategoryResult(_ContractBase):
    """One isolated analyzer's complete, score-engine-ready output."""

    analysis_id: str = Field(min_length=1, max_length=128)
    analyzer_id: str = Field(min_length=1, max_length=128)
    analyzer_version: str = Field(min_length=1, max_length=128)
    category: HealthCategory
    assessment_profile: AssessmentProfile = AssessmentProfile.PUBLIC
    used_sources: tuple[str, ...] = ()
    capability_states: tuple[CapabilityStatus, ...] = ()
    status: CategoryStatus
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    metrics: tuple[Metric, ...] = ()
    findings: tuple[Finding, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    coverage: Coverage
    confidence: Confidence
    limitations: tuple[Limitation, ...] = ()
    diagnostics_digest: str | None = Field(default=None, max_length=128)
    score_signals: dict[str, int] = Field(default_factory=dict)
    source_versions: dict[str, str] = Field(default_factory=dict)

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analysis_id")
    )
    _analyzer_id = field_validator("analyzer_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analyzer_id")
    )
    _analyzer_version = field_validator("analyzer_version", mode="before")(
        lambda value: _normalize_id(value, field_name="analyzer_version")
    )
    _diagnostics_digest = field_validator("diagnostics_digest", mode="before")(
        lambda value: None if value is None else _normalize_digest(value, field_name="diagnostics_digest")
    )
    _used_sources = field_validator("used_sources", mode="before")(
        lambda value: _stable_ids(value, field_name="used_sources")
    )

    @field_validator("score_signals", mode="before")
    @classmethod
    def _bounded_score_signals(cls, value: object) -> dict[str, int]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("score_signals must be a mapping")
        allowed = {
            "active_findings",
            "critical_findings",
            "high_findings",
            "confirmed_secret_count",
            "secret_findings",
        }
        normalized: dict[str, int] = {}
        for key, raw_count in value.items():
            if key not in allowed:
                raise ValueError(f"unsupported score signal: {key}")
            if not isinstance(raw_count, int) or isinstance(raw_count, bool) or not 0 <= raw_count <= 1_000_000:
                raise ValueError(f"score signal {key} must be a bounded integer")
            normalized[key] = raw_count
        return normalized

    @model_validator(mode="after")
    def _validate_result(self) -> CategoryResult:
        if self.status in {CategoryStatus.SKIPPED, CategoryStatus.ERROR} and self.score is not None:
            raise ValueError(f"score must be absent when status is {self.status.value}")
        evidence_ids = {item.evidence_id for item in self.evidence}
        referenced = {item_id for finding in self.findings for item_id in finding.evidence_ids}
        missing = sorted(referenced - evidence_ids)
        if missing:
            raise ValueError(f"findings reference unknown evidence IDs: {missing!r}")
        object.__setattr__(self, "metrics", tuple(sorted(self.metrics, key=lambda item: item.name)))
        object.__setattr__(self, "findings", tuple(sorted(self.findings, key=lambda item: item.finding_id or "")))
        object.__setattr__(self, "evidence", tuple(sorted(self.evidence, key=lambda item: item.evidence_id)))
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations, key=lambda item: item.code)))
        return self

    def digest(self) -> str:
        """Keep legacy default-result digests stable while hashing new context."""

        payload = self.model_dump(mode="json")
        if self.assessment_profile is AssessmentProfile.PUBLIC and not self.used_sources and not self.capability_states:
            payload.pop("assessment_profile", None)
            payload.pop("used_sources", None)
            payload.pop("capability_states", None)
        return contract_digest(payload)


class AnalysisStatus(_ContractBase):
    """Lifecycle state and per-analyzer completion state for one analysis."""

    analysis_id: str = Field(min_length=1, max_length=128)
    state: AnalysisState
    completed_analyzer_ids: tuple[str, ...] = ()
    failed_analyzer_ids: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=1000)

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analysis_id")
    )
    _completed_analyzer_ids = field_validator("completed_analyzer_ids", mode="before")(
        lambda value: _stable_ids(value, field_name="completed_analyzer_ids")
    )
    _failed_analyzer_ids = field_validator("failed_analyzer_ids", mode="before")(
        lambda value: _stable_ids(value, field_name="failed_analyzer_ids")
    )
    _started_at = field_validator("started_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="started_at")
    )
    _finished_at = field_validator("finished_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="finished_at")
    )

    @model_validator(mode="after")
    def _valid_transition(self) -> AnalysisStatus:
        overlap = set(self.completed_analyzer_ids) & set(self.failed_analyzer_ids)
        if overlap:
            raise ValueError(f"analyzer cannot be both completed and failed: {sorted(overlap)!r}")
        if self.finished_at is not None and self.started_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must be after started_at")
        if self.state == AnalysisState.FAILED and not self.failed_analyzer_ids and not self.reason:
            raise ValueError("failed analysis requires failed analyzers or a reason")
        return self


class ScoreInput(_ContractBase):
    """Explicit six-slot input accepted by the frozen Repo Health score engine."""

    analysis_id: str = Field(min_length=1, max_length=128)
    repository: RepositoryRef
    assessment_profile: AssessmentProfile = AssessmentProfile.PUBLIC
    used_sources: tuple[str, ...] = ()
    capability_states: tuple[CapabilityStatus, ...] = ()
    documentation: CategoryResult | None = None
    activity: CategoryResult | None = None
    issues: CategoryResult | None = None
    cicd: CategoryResult | None = None
    security: CategoryResult | None = None
    code_health: CategoryResult | None = None
    score_engine_version: str = Field(min_length=1, max_length=128)
    policy_digest: str | None = Field(default=None, max_length=128)
    weights: dict[str, float] | None = None

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analysis_id")
    )
    _score_engine_version = field_validator("score_engine_version", mode="before")(
        lambda value: _normalize_id(value, field_name="score_engine_version")
    )
    _policy_digest = field_validator("policy_digest", mode="before")(
        lambda value: None if value is None else _normalize_digest(value, field_name="policy_digest")
    )
    _used_sources = field_validator("used_sources", mode="before")(
        lambda value: _stable_ids(value, field_name="used_sources")
    )

    @model_validator(mode="after")
    def _same_analysis_id(self) -> ScoreInput:
        for category in (
            self.documentation,
            self.activity,
            self.issues,
            self.cicd,
            self.security,
            self.code_health,
        ):
            if category is not None and category.assessment_profile is not self.assessment_profile:
                raise ValueError("all CategoryResult values must use the ScoreInput assessment_profile")
        for category in (
            self.documentation,
            self.activity,
            self.issues,
            self.cicd,
            self.security,
            self.code_health,
        ):
            if category is not None and category.analysis_id != self.analysis_id:
                raise ValueError("all CategoryResult values must use the ScoreInput analysis_id")
        return self


class ScoreBreakdown(_ContractBase):
    """Explainable, deterministic output of the frozen Score v1 formula."""

    category_scores: dict[str, float | None] = Field(default_factory=dict)
    category_statuses: dict[str, str] = Field(default_factory=dict)
    category_coverage: dict[str, float] = Field(default_factory=dict)
    category_confidence: dict[str, float] = Field(default_factory=dict)
    category_quality: dict[str, float] = Field(default_factory=dict)
    contributions: tuple[dict[str, Any], ...] = ()
    excluded_categories: tuple[str, ...] = ()
    applied_caps: tuple[dict[str, Any], ...] = ()


class RepoHealthResult(_ContractBase):
    """Serializable public-domain result with explicit category projections."""

    analysis_id: str = Field(min_length=1, max_length=128)
    repository: RepositoryRef
    assessment_profile: AssessmentProfile = AssessmentProfile.PUBLIC
    used_sources: tuple[str, ...] = ()
    capability_states: tuple[CapabilityStatus, ...] = ()
    status: AnalysisStatus
    overall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    score_before_caps: float | None = Field(default=None, ge=0.0, le=100.0)
    score_engine_version: str = Field(min_length=1, max_length=128)
    policy_digest: str | None = Field(default=None, max_length=128)
    score_config_digest: str | None = Field(default=None, max_length=128)
    presentation_state: Literal["SCORE", "PROVISIONAL_SCORE", "INSUFFICIENT_DATA"] = "INSUFFICIENT_DATA"
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage_k: float = Field(default=0.0, ge=0.0, le=1.0)
    applied_caps: tuple[dict[str, Any], ...] = ()
    limitations: tuple[Limitation, ...] = ()
    score_status: Literal["pass", "warn", "fail", "inconclusive"] = "inconclusive"
    breakdown: ScoreBreakdown | None = None
    documentation: CategoryResult | None = None
    activity: CategoryResult | None = None
    issues: CategoryResult | None = None
    cicd: CategoryResult | None = None
    security: CategoryResult | None = None
    code_health: CategoryResult | None = None

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analysis_id")
    )
    _score_engine_version = field_validator("score_engine_version", mode="before")(
        lambda value: _normalize_id(value, field_name="score_engine_version")
    )
    _policy_digest = field_validator("policy_digest", "score_config_digest", mode="before")(
        lambda value, info: None if value is None else _normalize_digest(value, field_name=info.field_name)
    )
    _used_sources = field_validator("used_sources", mode="before")(
        lambda value: _stable_ids(value, field_name="used_sources")
    )

    @model_validator(mode="after")
    def _same_analysis_id(self) -> RepoHealthResult:
        if self.status.analysis_id != self.analysis_id:
            raise ValueError("status and result must use the same analysis_id")
        for category in (
            self.documentation,
            self.activity,
            self.issues,
            self.cicd,
            self.security,
            self.code_health,
        ):
            if category is not None and category.analysis_id != self.analysis_id:
                raise ValueError("all CategoryResult values must use the result analysis_id")
            if category is not None and category.assessment_profile is not self.assessment_profile:
                raise ValueError("all CategoryResult values must use the result assessment_profile")
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations, key=lambda item: item.code)))
        return self


class AnalysisEnvelope(_ContractBase):
    """Immutable, replayable boundary persisted for one analysis attempt."""

    analysis_id: str = Field(min_length=1, max_length=128)
    request: AnalysisRequest
    assessment_profile: AssessmentProfile = AssessmentProfile.PUBLIC
    facts: RepositoryFacts | None = None
    facts_digest: str | None = Field(default=None, max_length=128)
    category_results: tuple[CategoryResult, ...] = ()
    score: RepoHealthResult | None = None
    status: AnalysisStatus
    idempotency_key: str = Field(min_length=1, max_length=128)
    policy_digest: str | None = Field(default=None, max_length=128)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_id(value, field_name="analysis_id")
    )
    _idempotency_key = field_validator("idempotency_key", mode="before")(
        lambda value: _normalize_id(value, field_name="idempotency_key")
    )
    _facts_digest = field_validator("facts_digest", mode="before")(
        lambda value: None if value is None else _normalize_digest(value, field_name="facts_digest")
    )
    _policy_digest = field_validator("policy_digest", mode="before")(
        lambda value: None if value is None else _normalize_digest(value, field_name="policy_digest")
    )
    _created_at = field_validator("created_at", mode="after")(
        lambda value: _normalize_utc(value, field_name="created_at")
    )
    _started_at = field_validator("started_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="started_at")
    )
    _finished_at = field_validator("finished_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="finished_at")
    )

    @field_validator("tool_versions", mode="before")
    @classmethod
    def _bounded_tool_versions(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("tool_versions must be a mapping")
        normalized: dict[str, str] = {}
        for key, raw_version in value.items():
            name = _normalize_key(key, field_name="tool_versions key")
            if not isinstance(raw_version, str) or not raw_version.strip() or len(raw_version.strip()) > 128:
                raise ValueError("tool_versions values must be bounded non-empty strings")
            normalized[name] = raw_version.strip()
        return normalized

    @model_validator(mode="after")
    def _envelope_is_consistent(self) -> AnalysisEnvelope:
        if self.request.analysis_id != self.analysis_id:
            raise ValueError("request and envelope must use the same analysis_id")
        if self.request.assessment_profile is not self.assessment_profile:
            raise ValueError("request and envelope must use the same assessment_profile")
        if self.status.analysis_id != self.analysis_id:
            raise ValueError("status and envelope must use the same analysis_id")
        if self.facts is not None:
            calculated = self.facts.digest()
            if self.facts_digest is not None and self.facts_digest != calculated:
                raise ValueError("facts_digest does not match normalized RepositoryFacts")
            object.__setattr__(self, "facts_digest", calculated)
        for result in self.category_results:
            if result.analysis_id != self.analysis_id:
                raise ValueError("category results must use the envelope analysis_id")
        if self.score is not None and self.score.analysis_id != self.analysis_id:
            raise ValueError("score and envelope must use the same analysis_id")
        if self.score is not None and self.score.assessment_profile is not self.assessment_profile:
            raise ValueError("score and envelope must use the same assessment_profile")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise ValueError("finished_at must be after created_at")
        return self


__all__ = [
    "AnalysisEnvelope",
    "AnalysisState",
    "AnalysisStatus",
    "AnalyzerInput",
    "AppSecScanState",
    "AssessmentProfile",
    "CapabilityStatus",
    "CategoryResult",
    "CategoryStatus",
    "CicdFacts",
    "CodeHealthFacts",
    "CollectionState",
    "Confidence",
    "Coverage",
    "DocumentationFacts",
    "Evidence",
    "FactGroup",
    "FactObservation",
    "Finding",
    "FindingLocation",
    "GitFacts",
    "HealthCategory",
    "IssuesFacts",
    "Limitation",
    "Metric",
    "ProviderCapabilityState",
    "RepoHealthResult",
    "RepositoryFacts",
    "ScoreBreakdown",
    "ScoreInput",
    "SecurityFacts",
    "SourceStatus",
]
