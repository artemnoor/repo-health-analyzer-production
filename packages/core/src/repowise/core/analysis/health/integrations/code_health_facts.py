"""Normalized facts and policy for the optional Code Health engines.

The source adapters deliberately terminate their external contracts here.  The
Code Health scorer only consumes these immutable, bounded observations and
never sees SonarQube responses, process output, or git-sizer objects.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import structlog

log = structlog.get_logger("health.code_health.facts")

CODE_HEALTH_CONFIG_RELATIVE = Path("config/analyzers/code-health.yaml")
CODE_HEALTH_POLICY_REVISION = "code-health-v1"
CODE_HEALTH_SCHEMA_VERSION = "repowise-code-health-v1"


class CodeHealthStatus(StrEnum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def bounded(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in {float("inf"), float("-inf")}:
        return default
    return max(0.0, min(1.0, number))


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def stable_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _safe_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType({str(key): item for key, item in (value or {}).items()})


@dataclass(frozen=True)
class CodeHealthPolicy:
    """Resolved, versioned policy shared by all Code Health adapters."""

    root: Path
    revision: str = CODE_HEALTH_POLICY_REVISION
    source_commit: str = "unknown"
    enabled: bool = True
    old_todo_days: int = 180
    max_source_file_bytes: int = 2_000_000
    max_source_files: int = 50_000
    max_findings: int = 100
    git_sizer_timeout_seconds: float = 120.0
    git_sizer_output_cap_bytes: int = 16 * 1024 * 1024
    partial_score_cap: float = 80.0
    component_weights: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                "maintainability_debt": 0.35,
                "complexity": 0.15,
                "duplication": 0.15,
                "hotspots_churn": 0.15,
                "todo_debt": 0.10,
                "git_structure": 0.10,
            }
        )
    )
    exclusions: tuple[str, ...] = (
        ".git/",
        "vendor/",
        "generated/",
        "build/",
        "dist/",
        "out/",
        "coverage/",
        "node_modules/",
        ".venv/",
        "**/*.min.js",
        "**/*.min.css",
    )
    maintainability_rating_scores: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {"A": 100.0, "B": 85.0, "C": 70.0, "D": 45.0, "E": 15.0}
        )
    )
    sonar_metric_aliases: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType(
            {
                "maintainability_rating": ("maintainability_rating", "sqale_rating"),
                "code_smells": ("code_smells",),
                "technical_debt_minutes": ("technical_debt_minutes", "sqale_index"),
                "remediation_effort": ("remediation_effort", "effort"),
                "cognitive_complexity": ("cognitive_complexity",),
                "cyclomatic_complexity": ("cyclomatic_complexity", "complexity"),
                "duplicated_lines_density": ("duplicated_lines_density",),
                "duplicated_lines": ("duplicated_lines",),
                "ncloc": ("ncloc", "lines_of_code"),
                "reliability_bugs": ("reliability_bugs", "bugs"),
                "coverage": ("coverage",),
            }
        )
    )

    @property
    def digest(self) -> str:
        payload = {
            "revision": self.revision,
            "source_commit": self.source_commit,
            "enabled": self.enabled,
            "old_todo_days": self.old_todo_days,
            "limits": {
                "max_source_file_bytes": self.max_source_file_bytes,
                "max_source_files": self.max_source_files,
                "max_findings": self.max_findings,
                "git_sizer_timeout_seconds": self.git_sizer_timeout_seconds,
                "git_sizer_output_cap_bytes": self.git_sizer_output_cap_bytes,
                "partial_score_cap": self.partial_score_cap,
            },
            "weights": dict(self.component_weights),
            "exclusions": self.exclusions,
            "rating_scores": dict(self.maintainability_rating_scores),
            "metric_aliases": {key: tuple(value) for key, value in self.sonar_metric_aliases.items()},
        }
        return stable_digest(payload)

    @classmethod
    def from_mapping(cls, root: Path, raw: Mapping[str, Any]) -> CodeHealthPolicy:
        policy = _mapping(raw.get("policy")) or raw
        weights_raw = _mapping(policy.get("component_weights")) or {}
        weights = {
            str(key): float(value)
            for key, value in weights_raw.items()
            if isinstance(value, (int, float)) and float(value) >= 0
        }
        defaults = dict(cls(root=root).component_weights)
        defaults.update(weights)
        exclusions_raw = policy.get("exclusions")
        exclusions = tuple(
            str(item).replace("\\", "/")
            for item in exclusions_raw
            if isinstance(item, str) and item.strip()
        ) if isinstance(exclusions_raw, Sequence) and not isinstance(exclusions_raw, (str, bytes)) else cls(root=root).exclusions
        limits = _mapping(policy.get("limits")) or {}
        sonar = _mapping(raw.get("sonar")) or {}
        aliases_raw = _mapping(sonar.get("metric_aliases")) or {}
        aliases = dict(cls(root=root).sonar_metric_aliases)
        for name, values in aliases_raw.items():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                aliases[str(name)] = tuple(str(value) for value in values if str(value).strip())
        rating_raw = _mapping(policy.get("maintainability_rating_scores")) or {}
        ratings = dict(cls(root=root).maintainability_rating_scores)
        ratings.update({str(key).upper(): float(value) for key, value in rating_raw.items() if isinstance(value, (int, float))})
        return cls(
            root=root,
            revision=str(raw.get("revision") or CODE_HEALTH_POLICY_REVISION),
            source_commit=str(raw.get("source_commit") or "unknown"),
            enabled=bool(raw.get("enabled", True)),
            old_todo_days=max(1, int(policy.get("old_todo_days", 180))),
            max_source_file_bytes=max(1, int(limits.get("max_source_file_bytes", 2_000_000))),
            max_source_files=max(1, int(limits.get("max_source_files", 50_000))),
            max_findings=max(1, int(limits.get("max_findings", 100))),
            git_sizer_timeout_seconds=max(1.0, float(limits.get("git_sizer_timeout_seconds", 120.0))),
            git_sizer_output_cap_bytes=max(1024, int(limits.get("git_sizer_output_cap_bytes", 16 * 1024 * 1024))),
            partial_score_cap=max(1.0, min(100.0, float(policy.get("partial_score_cap", 80.0)))),
            component_weights=MappingProxyType(defaults),
            exclusions=exclusions,
            maintainability_rating_scores=MappingProxyType(ratings),
            sonar_metric_aliases=MappingProxyType(aliases),
        )


def load_code_health_policy(root: Path | str | None = None) -> CodeHealthPolicy:
    root_path = Path(root or Path.cwd()).resolve()
    path = root_path / CODE_HEALTH_CONFIG_RELATIVE
    if not path.exists():
        log.info("code_health_policy_default", path=str(path), revision=CODE_HEALTH_POLICY_REVISION)
        return CodeHealthPolicy(root=root_path)
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("Code Health policy must be a mapping")
        policy = CodeHealthPolicy.from_mapping(root_path, raw)
        log.info("code_health_policy_loaded", revision=policy.revision, digest=policy.digest[:16])
        return policy
    except (OSError, TypeError, ValueError) as exc:
        log.error("code_health_policy_load_failed", error_type=type(exc).__name__)
        raise


@dataclass(frozen=True)
class CodeHealthEvidenceFact:
    source: str
    path: str | None = None
    line: int | None = None
    json_pointer: str | None = None
    subject: str | None = None
    rule: str | None = None
    severity: str | None = None
    value: float | int | str | None = None
    age_days: float | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class SonarIssueFact:
    issue_id: str
    rule: str | None
    issue_type: str
    severity: str | None
    component: str | None
    path: str | None
    line: int | None
    effort_minutes: float | None
    message: str | None = None


@dataclass(frozen=True)
class SonarFacts:
    status: CodeHealthStatus
    project_key: str | None = None
    analysis_id: str | None = None
    server_version: str | None = None
    scanner_version: str | None = None
    measures: Mapping[str, float | str] = field(default_factory=dict)
    components: tuple[Mapping[str, Any], ...] = ()
    issues: tuple[SonarIssueFact, ...] = ()
    coverage_status: CodeHealthStatus = CodeHealthStatus.NOT_APPLICABLE
    coverage_provenance: Mapping[str, Any] = field(default_factory=dict)
    source_snapshot_digest: str | None = None
    pages_fetched: int = 0
    pagination_complete: bool | None = None
    coverage: float = 0.0
    confidence: float = 0.0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[CodeHealthEvidenceFact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "measures", _safe_mapping(self.measures))
        object.__setattr__(self, "coverage_provenance", _safe_mapping(self.coverage_provenance))
        object.__setattr__(self, "diagnostics", _safe_mapping(self.diagnostics))
        object.__setattr__(self, "components", tuple(dict(item) for item in self.components))
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "coverage", bounded(self.coverage))
        object.__setattr__(self, "confidence", bounded(self.confidence))


@dataclass(frozen=True)
class GitStructureFacts:
    status: CodeHealthStatus
    tool_version: str = "unknown"
    json_version: str = "2"
    metrics: Mapping[str, float | int | str] = field(default_factory=dict)
    level_of_concern: Mapping[str, str] = field(default_factory=dict)
    evidence: tuple[CodeHealthEvidenceFact, ...] = ()
    source_snapshot_digest: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    coverage: float = 0.0
    confidence: float = 0.0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _safe_mapping(self.metrics))
        object.__setattr__(self, "level_of_concern", _safe_mapping(self.level_of_concern))
        object.__setattr__(self, "diagnostics", _safe_mapping(self.diagnostics))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "coverage", bounded(self.coverage))
        object.__setattr__(self, "confidence", bounded(self.confidence))


@dataclass(frozen=True)
class TodoFact:
    marker: str
    path: str
    line: int
    age_days: float | None = None
    blame_commit: str | None = None


@dataclass(frozen=True)
class TodoDebtFacts:
    status: CodeHealthStatus
    included_loc: int = 0
    todo_count: int = 0
    fixme_count: int = 0
    density_per_kloc: float | None = None
    old_count: int = 0
    old_ratio: float | None = None
    ages_days: tuple[float, ...] = ()
    facts: tuple[TodoFact, ...] = ()
    hotspot_count: int = 0
    source_files: int = 0
    excluded_files: int = 0
    coverage: float = 0.0
    confidence: float = 0.0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ages_days", tuple(float(value) for value in self.ages_days if float(value) >= 0))
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(self, "diagnostics", _safe_mapping(self.diagnostics))
        object.__setattr__(self, "coverage", bounded(self.coverage))
        object.__setattr__(self, "confidence", bounded(self.confidence))


@dataclass(frozen=True)
class CodeHealthFacts:
    status: CodeHealthStatus
    as_of_at: datetime
    policy_revision: str = CODE_HEALTH_POLICY_REVISION
    policy_digest: str = ""
    source_snapshot_digest: str | None = None
    sonar: SonarFacts | None = None
    git_structure: GitStructureFacts | None = None
    todo_debt: TodoDebtFacts | None = None
    baseline: Mapping[str, Any] = field(default_factory=dict)
    exclusions: Mapping[str, Any] = field(default_factory=dict)
    engine_statuses: Mapping[str, str] = field(default_factory=dict)
    engine_coverage: Mapping[str, float] = field(default_factory=dict)
    coverage: float = 0.0
    confidence: float = 0.0
    limitations: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of_at", utc(self.as_of_at) or self.as_of_at)
        object.__setattr__(self, "engine_statuses", _safe_mapping(self.engine_statuses))
        object.__setattr__(self, "engine_coverage", MappingProxyType({str(k): bounded(v) for k, v in self.engine_coverage.items()}))
        object.__setattr__(self, "baseline", _safe_mapping(self.baseline))
        object.__setattr__(self, "exclusions", _safe_mapping(self.exclusions))
        object.__setattr__(self, "diagnostics", _safe_mapping(self.diagnostics))
        object.__setattr__(self, "limitations", tuple(str(item) for item in self.limitations))
        object.__setattr__(self, "coverage", bounded(self.coverage))
        object.__setattr__(self, "confidence", bounded(self.confidence))

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "policy_revision": self.policy_revision,
            "policy_digest": self.policy_digest,
            "source_snapshot_digest": self.source_snapshot_digest,
            "baseline": dict(self.baseline),
            "exclusions": dict(self.exclusions),
            "engine_statuses": dict(self.engine_statuses),
            "engine_coverage": dict(self.engine_coverage),
            "coverage": self.coverage,
            "confidence": self.confidence,
            "limitations": self.limitations,
            "sonar_measures": sorted(self.sonar.measures) if self.sonar else [],
            "sonar_issue_count": len(self.sonar.issues) if self.sonar else 0,
            "git_structure_metrics": sorted(self.git_structure.metrics) if self.git_structure else [],
            "todo_count": (self.todo_debt.todo_count + self.todo_debt.fixme_count) if self.todo_debt else 0,
        }


def aggregate_status(statuses: Sequence[CodeHealthStatus]) -> CodeHealthStatus:
    usable = [status for status in statuses if status is not CodeHealthStatus.NOT_APPLICABLE]
    if not usable:
        return CodeHealthStatus.NOT_APPLICABLE
    if any(status is CodeHealthStatus.ERROR for status in usable):
        return CodeHealthStatus.PARTIAL if any(status is CodeHealthStatus.MEASURED for status in usable) else CodeHealthStatus.ERROR
    if any(status is CodeHealthStatus.PARTIAL for status in usable):
        return CodeHealthStatus.PARTIAL
    if all(status is CodeHealthStatus.UNAVAILABLE for status in usable):
        return CodeHealthStatus.UNAVAILABLE
    if any(status is CodeHealthStatus.UNAVAILABLE for status in usable):
        return CodeHealthStatus.PARTIAL
    return CodeHealthStatus.MEASURED


__all__ = [
    "CODE_HEALTH_CONFIG_RELATIVE",
    "CODE_HEALTH_POLICY_REVISION",
    "CODE_HEALTH_SCHEMA_VERSION",
    "CodeHealthEvidenceFact",
    "CodeHealthFacts",
    "CodeHealthPolicy",
    "CodeHealthStatus",
    "GitStructureFacts",
    "SonarFacts",
    "SonarIssueFact",
    "TodoDebtFacts",
    "TodoFact",
    "aggregate_status",
    "bounded",
    "load_code_health_policy",
    "stable_digest",
]
