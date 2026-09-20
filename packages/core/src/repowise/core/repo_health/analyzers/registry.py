"""Canonical Repo Health analyzer registry and ownership manifest."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts.requests import CONTRACT_SCHEMA_VERSION
from ..contracts.results import (
    AnalyzerInput,
    CategoryResult,
    HealthCategory,
)

CANONICAL_ANALYZER_IDS = (
    "repo-health.documentation",
    "repo-health.activity",
    "repo-health.issues",
    "repo-health.cicd",
    "repo-health.security",
    "repo-health.code-health",
)

_CATEGORY_BY_ID = {
    "repo-health.documentation": HealthCategory.DOCUMENTATION,
    "repo-health.activity": HealthCategory.ACTIVITY,
    "repo-health.issues": HealthCategory.ISSUES,
    "repo-health.cicd": HealthCategory.CICD,
    "repo-health.security": HealthCategory.SECURITY,
    "repo-health.code-health": HealthCategory.CODE_HEALTH,
}


class AnalyzerFactory(Protocol):
    def __call__(self, analyzer_input: AnalyzerInput) -> CategoryResult: ...


class AnalyzerSpec(BaseModel):
    """Serializable metadata for one canonical deployable analyzer boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    category: HealthCategory
    fact_group: str = Field(min_length=1, max_length=128)
    policy: str = Field(min_length=1, max_length=256)
    public_result: Literal["CategoryResult"] = "CategoryResult"
    supported_modes: tuple[str, ...] = ("fast", "full", "offline")
    capabilities: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=120.0, gt=0, le=86_400)
    cache_policy: Literal["none", "read", "write", "read_write"] = "read_write"
    aliases: tuple[str, ...] = ()

    @field_validator("id", mode="before")
    @classmethod
    def _bounded_id(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("analyzer id must be a non-empty string")
        return value.strip().lower()

    @field_validator("supported_modes", "capabilities", "aliases", mode="before")
    @classmethod
    def _stable_names(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        return tuple(sorted({str(item).strip().lower() for item in value if str(item).strip()}))

    @model_validator(mode="after")
    def _matches_canonical_category(self) -> AnalyzerSpec:
        if self.id not in _CATEGORY_BY_ID:
            raise ValueError(f"unknown canonical analyzer id: {self.id}")
        if self.category is not _CATEGORY_BY_ID[self.id]:
            raise ValueError(f"analyzer category does not match canonical id: {self.id}")
        if self.id in self.aliases:
            raise ValueError("canonical analyzer cannot alias itself")
        return self


class AnalyzerOwnership(BaseModel):
    """Normative current-ID ownership record used by health-edge aliases."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    current_id: str = Field(min_length=1, max_length=128)
    canonical_id: str = Field(min_length=1, max_length=128)
    category: HealthCategory
    input_fact_group: str = Field(min_length=1, max_length=128)
    policy: str = Field(min_length=1, max_length=256)
    public_result: Literal["CategoryResult"] = "CategoryResult"
    kind: Literal["canonical", "alias", "auxiliary"]
    removal_phase: str | None = Field(default=None, max_length=64)


class RegistryResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    requested_id: str = Field(min_length=1, max_length=128)
    canonical_id: str = Field(min_length=1, max_length=128)
    category: HealthCategory
    kind: Literal["canonical", "alias", "auxiliary"]


class CanonicalAnalyzerRegistry:
    """Six-entry registry with explicit factory injection and no discovery."""

    def __init__(self, specs: Iterable[AnalyzerSpec] = ()) -> None:
        self._specs: dict[str, AnalyzerSpec] = {}
        self._factories: dict[str, AnalyzerFactory] = {}
        for spec in specs:
            self.register_spec(spec)

    def register_spec(self, spec: AnalyzerSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"canonical analyzer id already registered: {spec.id}")
        self._specs[spec.id] = spec

    def register_factory(self, analyzer_id: str, factory: AnalyzerFactory) -> None:
        if analyzer_id not in self._specs:
            raise KeyError(f"unknown canonical analyzer id: {analyzer_id}")
        if not callable(factory):
            raise TypeError(f"factory for {analyzer_id!r} must be callable")
        self._factories[analyzer_id] = factory

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def definitions(self) -> tuple[AnalyzerSpec, ...]:
        return tuple(self._specs[item] for item in self.ids())

    def get(self, analyzer_id: str) -> tuple[AnalyzerSpec, AnalyzerFactory | None] | None:
        spec = self._specs.get(analyzer_id)
        return None if spec is None else (spec, self._factories.get(analyzer_id))

    def run(self, analyzer_id: str, analyzer_input: AnalyzerInput) -> CategoryResult:
        entry = self.get(analyzer_id)
        if entry is None:
            raise KeyError(f"unknown canonical analyzer id: {analyzer_id}")
        _spec, factory = entry
        if factory is None:
            raise RuntimeError(f"no factory registered for canonical analyzer: {analyzer_id}")
        result = factory(analyzer_input)
        if result.category is not _CATEGORY_BY_ID[analyzer_id]:
            raise ValueError(f"factory returned a result for the wrong category: {analyzer_id}")
        if result.analyzer_id != analyzer_id:
            raise ValueError(f"factory returned a result for the wrong analyzer: {analyzer_id}")
        return result

    def validate(self) -> None:
        if self.ids() != tuple(sorted(CANONICAL_ANALYZER_IDS)):
            raise ValueError("canonical registry must contain exactly six Repo Health analyzers")
        categories = [self._specs[item].category for item in self.ids()]
        if len(categories) != len(set(categories)):
            raise ValueError("canonical registry cannot contain duplicate categories")


def _spec(
    analyzer_id: str,
    *,
    version: str,
    fact_group: str,
    policy: str,
    capabilities: tuple[str, ...],
    aliases: tuple[str, ...],
    timeout_seconds: float,
) -> AnalyzerSpec:
    return AnalyzerSpec(
        id=analyzer_id,
        version=version,
        category=_CATEGORY_BY_ID[analyzer_id],
        fact_group=fact_group,
        policy=policy,
        capabilities=capabilities,
        aliases=aliases,
        timeout_seconds=timeout_seconds,
    )


CANONICAL_SPECS = (
    _spec(
        "repo-health.documentation",
        version="repo-health-documentation-v1",
        fact_group="documentation",
        policy="documentation-calibration-v2",
        capabilities=("documentation.files", "vale"),
        aliases=("vale.documentation",),
        timeout_seconds=180,
    ),
    _spec(
        "repo-health.activity",
        version="repo-health-activity-v1",
        fact_group="git",
        policy="activity-calibration-v2",
        capabilities=("git.history", "pydriller"),
        aliases=("chaoss.activity",),
        timeout_seconds=180,
    ),
    _spec(
        "repo-health.issues",
        version="repo-health-issues-v1",
        fact_group="issues",
        policy="issues-calibration-v2",
        capabilities=("sourcecraft.issues",),
        aliases=("chaoss.issues_prs",),
        timeout_seconds=120,
    ),
    _spec(
        "repo-health.cicd",
        version="repo-health-cicd-v1",
        fact_group="cicd",
        policy="cicd-calibration-v2",
        capabilities=("sourcecraft.cicd",),
        aliases=("cicd.sourcecraft",),
        timeout_seconds=120,
    ),
    _spec(
        "repo-health.security",
        version="repo-health-security-v1",
        fact_group="security",
        policy="security-v1",
        capabilities=("sourcecraft.appsec.rest",),
        aliases=("sourcecraft.appsec",),
        timeout_seconds=90,
    ),
    _spec(
        "repo-health.code-health",
        version="repo-health-code-health-v1",
        fact_group="code_health",
        policy="code-health-v1",
        capabilities=("sonarqube", "git-sizer", "git.history"),
        aliases=("repowise.health",),
        timeout_seconds=300,
    ),
)


_AUXILIARY_OWNERSHIP = (
    ("chaoss.dependencies", "repo-health.activity", HealthCategory.ACTIVITY, "activity-calibration-v2"),
    ("chaoss.releases", "repo-health.activity", HealthCategory.ACTIVITY, "activity-calibration-v2"),
    ("criticality.importance", "repo-health.code-health", HealthCategory.CODE_HEALTH, "code-health-v1"),
    ("dependencies.enrichment", "repo-health.code-health", HealthCategory.CODE_HEALTH, "code-health-v1"),
    ("events.temporal", "repo-health.activity", HealthCategory.ACTIVITY, "activity-calibration-v2"),
    ("forge.community", "repo-health.activity", HealthCategory.ACTIVITY, "activity-calibration-v2"),
    ("forge.metadata", "repo-health.activity", HealthCategory.ACTIVITY, "activity-calibration-v2"),
    ("graal.external_tools", "repo-health.code-health", HealthCategory.CODE_HEALTH, "code-health-v1"),
    ("identity.enrichment", "repo-health.activity", HealthCategory.ACTIVITY, "activity-calibration-v2"),
    ("qlty.check", "repo-health.code-health", HealthCategory.CODE_HEALTH, "code-health-v1"),
    ("repohealth.baseline", "repo-health.code-health", HealthCategory.CODE_HEALTH, "code-health-v1"),
    ("scorecard.local", "repo-health.security", HealthCategory.SECURITY, "security-v1"),
    ("sokrates.analysis", "repo-health.code-health", HealthCategory.CODE_HEALTH, "code-health-v1"),
)


def _build_ownership_manifest() -> tuple[AnalyzerOwnership, ...]:
    records: list[AnalyzerOwnership] = []
    for spec in CANONICAL_SPECS:
        records.append(
            AnalyzerOwnership(
                current_id=spec.id,
                canonical_id=spec.id,
                category=spec.category,
                input_fact_group=spec.fact_group,
                policy=spec.policy,
                kind="canonical",
                removal_phase=None,
            )
        )
        for alias in spec.aliases:
            records.append(
                AnalyzerOwnership(
                    current_id=alias,
                    canonical_id=spec.id,
                    category=spec.category,
                    input_fact_group=spec.fact_group,
                    policy=spec.policy,
                    kind="alias",
                    removal_phase="phase-09-verification-rollout",
                )
            )
    for current_id, canonical_id, category, policy in _AUXILIARY_OWNERSHIP:
        records.append(
            AnalyzerOwnership(
                current_id=current_id,
                canonical_id=canonical_id,
                category=category,
                input_fact_group=category.value,
                policy=policy,
                kind="auxiliary",
                removal_phase="phase-07-cleanup-legal",
            )
        )
    return tuple(sorted(records, key=lambda item: item.current_id))


OWNERSHIP_MANIFEST = _build_ownership_manifest()


def _validate_manifest() -> None:
    current_ids = [item.current_id for item in OWNERSHIP_MANIFEST]
    if len(current_ids) != len(set(current_ids)):
        raise ValueError("analyzer ownership manifest contains duplicate current IDs")
    canonical_targets = {item.canonical_id for item in OWNERSHIP_MANIFEST}
    if set(CANONICAL_ANALYZER_IDS) - canonical_targets:
        raise ValueError("analyzer ownership manifest has an unowned canonical ID")
    for item in OWNERSHIP_MANIFEST:
        if item.canonical_id not in CANONICAL_ANALYZER_IDS:
            raise ValueError(f"ownership points outside canonical registry: {item.current_id}")


_validate_manifest()

canonical_registry = CanonicalAnalyzerRegistry(CANONICAL_SPECS)
canonical_registry.validate()
_MANIFEST_BY_ID = {item.current_id: item for item in OWNERSHIP_MANIFEST}


def resolve_analyzer_id(analyzer_id: str) -> RegistryResolution:
    """Resolve a current/provider ID to exactly one canonical category ID."""

    record = _MANIFEST_BY_ID.get(analyzer_id)
    if record is None:
        raise KeyError(f"unknown analyzer ID: {analyzer_id}")
    return RegistryResolution(
        requested_id=record.current_id,
        canonical_id=record.canonical_id,
        category=record.category,
        kind=record.kind,
    )


__all__ = [
    "CANONICAL_ANALYZER_IDS",
    "CANONICAL_SPECS",
    "OWNERSHIP_MANIFEST",
    "AnalyzerFactory",
    "AnalyzerOwnership",
    "AnalyzerSpec",
    "CanonicalAnalyzerRegistry",
    "RegistryResolution",
    "canonical_registry",
    "resolve_analyzer_id",
]
