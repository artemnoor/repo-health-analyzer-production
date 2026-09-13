"""Public integration contract for all repository-health analyzers."""

from .chaoss_adapter import register_chaoss_adapters
from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    CachePolicy,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    MetricValue,
)
from .dependency_adapter import (
    DEPENDENCY_ANALYZER_ID,
    DEPENDENCY_DEFINITION,
    DependencyAdapter,
    DependencyEdge,
    DependencyFact,
    register_dependency_adapters,
)
from .finding_merge import deduplicate_findings
from .forge_adapter import (
    FORGE_COMMUNITY_DEFINITION,
    FORGE_METADATA_DEFINITION,
    ForgeAdapter,
    register_forge_adapters,
)
from .identity_adapter import (
    IDENTITY_ANALYZER_ID,
    IDENTITY_DEFINITION,
    IdentityAdapter,
    IdentityEvidence,
    IdentityMatch,
    IdentityResolver,
    register_identity_adapters,
)
from .native_adapters import (
    CRITICALITY_DEFINITION,
    QLTY_DEFINITION,
    REPOHEALTH_DEFINITION,
    SCORECARD_DEFINITION,
    SOKRATES_DEFINITION,
    register_native_adapters,
)
from .registry import AnalyzerRegistry, PlannedAnalyzer, registry
from .repowise_adapter import (
    REPOWISE_ANALYZER_ID,
    REPOWISE_DEFINITION,
    RepoWiseAdapter,
    register_repowise,
)
from .temporal_adapter import (
    TEMPORAL_ANALYZER_ID,
    TEMPORAL_DEFINITION,
    EventNormalizer,
    MaterializedRollup,
    NormalizedFact,
    TemporalAdapter,
    TemporalWindow,
    build_temporal_window,
    materialized_rollups,
    register_temporal_adapters,
)

register_repowise(registry)
register_native_adapters(registry)
register_forge_adapters(registry)
register_chaoss_adapters(registry)
register_temporal_adapters(registry)
register_identity_adapters(registry)
register_dependency_adapters(registry)

__all__ = [
    "CRITICALITY_DEFINITION",
    "DEPENDENCY_ANALYZER_ID",
    "DEPENDENCY_DEFINITION",
    "FORGE_COMMUNITY_DEFINITION",
    "FORGE_METADATA_DEFINITION",
    "IDENTITY_ANALYZER_ID",
    "IDENTITY_DEFINITION",
    "QLTY_DEFINITION",
    "REPOHEALTH_DEFINITION",
    "REPOWISE_ANALYZER_ID",
    "REPOWISE_DEFINITION",
    "SCORECARD_DEFINITION",
    "SOKRATES_DEFINITION",
    "TEMPORAL_ANALYZER_ID",
    "TEMPORAL_DEFINITION",
    "AnalyzerContext",
    "AnalyzerDefinition",
    "AnalyzerRegistry",
    "AnalyzerResult",
    "AnalyzerStatus",
    "CachePolicy",
    "DependencyAdapter",
    "DependencyEdge",
    "DependencyFact",
    "EventNormalizer",
    "EvidenceRef",
    "Finding",
    "FindingLocation",
    "ForgeAdapter",
    "IdentityAdapter",
    "IdentityEvidence",
    "IdentityMatch",
    "IdentityResolver",
    "Limitation",
    "MaterializedRollup",
    "MetricValue",
    "NormalizedFact",
    "PlannedAnalyzer",
    "RepoWiseAdapter",
    "TemporalAdapter",
    "TemporalWindow",
    "build_temporal_window",
    "deduplicate_findings",
    "materialized_rollups",
    "register_chaoss_adapters",
    "register_dependency_adapters",
    "register_forge_adapters",
    "register_identity_adapters",
    "register_native_adapters",
    "register_repowise",
    "register_temporal_adapters",
    "registry",
]
