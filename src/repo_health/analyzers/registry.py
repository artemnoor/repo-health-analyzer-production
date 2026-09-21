"""Canonical registry for the six independent Repo Health analyzers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts.requests import CONTRACT_SCHEMA_VERSION
from ..contracts.results import AnalyzerInput, CategoryResult, HealthCategory

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

    @field_validator("id", mode="before")
    @classmethod
    def _bounded_id(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("analyzer id must be a non-empty string")
        return value.strip().lower()

    @field_validator("supported_modes", "capabilities", mode="before")
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
        return self


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
    timeout_seconds: float,
) -> AnalyzerSpec:
    return AnalyzerSpec(
        id=analyzer_id,
        version=version,
        category=_CATEGORY_BY_ID[analyzer_id],
        fact_group=fact_group,
        policy=policy,
        capabilities=capabilities,
        timeout_seconds=timeout_seconds,
    )


CANONICAL_SPECS = (
    _spec(
        "repo-health.documentation",
        version="repo-health-documentation-v1",
        fact_group="documentation",
        policy="documentation-calibration-v2",
        capabilities=("documentation.files", "vale"),
        timeout_seconds=180,
    ),
    _spec(
        "repo-health.activity",
        version="repo-health-activity-v1",
        fact_group="git",
        policy="activity-calibration-v2",
        capabilities=("git.history", "pydriller"),
        timeout_seconds=180,
    ),
    _spec(
        "repo-health.issues",
        version="repo-health-issues-v1",
        fact_group="issues",
        policy="issues-sourcecraft-policy-v1",
        capabilities=("sourcecraft.issues",),
        timeout_seconds=120,
    ),
    _spec(
        "repo-health.cicd",
        version="repo-health-cicd-v1",
        fact_group="cicd",
        policy="cicd-calibration-v2",
        capabilities=("sourcecraft.cicd",),
        timeout_seconds=120,
    ),
    _spec(
        "repo-health.security",
        version="repo-health-security-v1",
        fact_group="security",
        policy="security-appsec-v1",
        capabilities=("sourcecraft.appsec.rest",),
        timeout_seconds=90,
    ),
    _spec(
        "repo-health.code-health",
        version="repo-health-code-health-v1",
        fact_group="code_health",
        policy="code-health-calibration-v2",
        capabilities=("sonarqube", "git-sizer", "git.history"),
        timeout_seconds=300,
    ),
)


canonical_registry = CanonicalAnalyzerRegistry(CANONICAL_SPECS)
canonical_registry.validate()


def register_default_factories(registry: CanonicalAnalyzerRegistry = canonical_registry) -> CanonicalAnalyzerRegistry:
    """Explicitly wire the six local analyzers from a composition root."""
    from .activity.factory import analyze as activity
    from .cicd.factory import analyze as cicd
    from .code_health.factory import analyze as code_health
    from .documentation.factory import analyze as documentation
    from .issues.factory import analyze as issues
    from .security.factory import analyze as security

    factories = {
        "repo-health.documentation": documentation,
        "repo-health.activity": activity,
        "repo-health.issues": issues,
        "repo-health.cicd": cicd,
        "repo-health.security": security,
        "repo-health.code-health": code_health,
    }
    for analyzer_id, factory in factories.items():
        registry.register_factory(analyzer_id, factory)
    return registry


__all__ = [
    "CANONICAL_ANALYZER_IDS",
    "CANONICAL_SPECS",
    "AnalyzerFactory",
    "AnalyzerSpec",
    "CanonicalAnalyzerRegistry",
    "canonical_registry",
    "register_default_factories",
]
