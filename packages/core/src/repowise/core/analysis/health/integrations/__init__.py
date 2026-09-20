"""Public integration contract for all repository-health analyzers."""

import time

import structlog

from .appsec_adapter import (
    APPSEC_ADAPTER_VERSION,
    APPSEC_SOURCE_COMMIT,
    AppSecDataStatus,
    AppSecFindingFact,
    AppSecFacts,
    SourceCraftAppSecAdapter,
    SourceCraftAppSecHTTPTransport,
    normalize_appsec_payload,
)
from .appsec_analyzer import (
    APPSEC_ANALYZER_ID,
    APPSEC_DEFINITION,
    APPSEC_DIMENSION,
    APPSEC_POLICY_REVISION,
    AppSecAnalyzer,
    appsec_adapter,
    register_appsec_adapter,
)
from .activity_analyzer import ACTIVITY_POLICY_VERSION, ActivityAnalyzer
from .chaoss_adapter import register_chaoss_adapters
from .cicd_analyzer import (
    CICD_ANALYZER_ID,
    CICD_DEFINITION,
    CICDAnalyzer,
    cicd_adapter,
    register_cicd_adapter,
)
from .cicd_facts import (
    CICDDataStatus,
    CICDFacts,
    CICDPolicy,
    CICDRetryRelation,
    CICDRunFact,
    CICDRunStatus,
    CICDWindowFacts,
    load_cicd_policy,
)
from .code_health_analyzer import CODE_HEALTH_ANALYZER_VERSION, CodeHealthAnalyzer
from .code_health_collector import (
    CODE_HEALTH_COLLECTOR_VERSION,
    CodeHealthFactsCollector,
    CodeHealthSourcePorts,
)
from .code_health_facts import (
    CodeHealthFacts,
    CodeHealthPolicy,
    CodeHealthStatus,
    GitStructureFacts,
    SonarFacts,
    TodoDebtFacts,
)
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
    Metric,
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
from .issues_analyzer import ISSUES_ANALYZER_VERSION, IssuesAnalyzer
from .issues_facts import (
    ActorClass,
    IssueCollectionFacts,
    IssueEventFact,
    IssueEventType,
    IssueFact,
    IssueMetricStatus,
    IssuesPolicy,
    IssueState,
    classify_actor,
    load_issues_policy,
    normalize_issue_inventory,
)
from .native_adapters import (
    CRITICALITY_DEFINITION,
    QLTY_DEFINITION,
    REPOHEALTH_DEFINITION,
    SCORECARD_DEFINITION,
    SOKRATES_DEFINITION,
    register_native_adapters,
)
from .pydriller_adapter import (
    PYDRILLER_CONFIG_RELATIVE,
    PYDRILLER_POLICY_REVISION,
    PYDRILLER_SOURCE_COMMIT,
    PYDRILLER_VALIDATED_VERSION,
    FailureKind,
    GitActivityBaseline,
    PyDrillerAdapter,
    PyDrillerExecutionStatus,
    PyDrillerFacts,
    PyDrillerPolicy,
    RefPolicy,
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
from .vale_adapter import (
    VALE_ANALYZER_ID,
    VALE_DEFINITION,
    ValeAdapter,
    register_vale_adapter,
    vale_adapter,
)

log = structlog.get_logger(__name__)


def register_all_health_adapters(
    target_registry: AnalyzerRegistry | None = None,
) -> AnalyzerRegistry:
    """Explicitly bootstrap the legacy health analyzer matrix once.

    The neutral registry remains empty until this health-edge function is
    called. Individual adapter registration functions are already idempotent;
    keeping the ordering here preserves the historical matrix ordering.
    """
    target = target_registry if target_registry is not None else registry
    before_ids = target.ids()
    started = time.perf_counter()
    log.info(
        "health_bootstrap_started",
        run_key=None,
        repository_id=None,
        repo_id=None,
        phase="bootstrap",
        completed_phases=(),
        status="running",
        duration_ms=0,
        failure_kind=None,
        analyzer_count=len(before_ids),
        analyzer_ids=before_ids,
        operation="register",
    )
    try:
        previous_registration_logging = target.emit_registration_logs
        target.emit_registration_logs = False
        try:
            register_repowise(target)
            register_native_adapters(target)
            register_forge_adapters(target)
            register_chaoss_adapters(target)
            register_temporal_adapters(target)
            register_identity_adapters(target)
            register_dependency_adapters(target)
            register_vale_adapter(target)
            register_cicd_adapter(target)
            register_appsec_adapter(target)
        finally:
            target.emit_registration_logs = previous_registration_logging
    except Exception as exc:
        log.error(
            "health_bootstrap_failed",
            run_key=None,
            repository_id=None,
            repo_id=None,
            phase="bootstrap",
            completed_phases=(),
            status="failed",
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            failure_kind=type(exc).__name__,
            analyzer_count=len(target.ids()),
            analyzer_ids=target.ids(),
        )
        log.debug(
            "health_bootstrap_failure_detail",
            run_key=None,
            repository_id=None,
            repo_id=None,
            phase="bootstrap",
            completed_phases=(),
            status="failed",
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            failure_kind=type(exc).__name__,
            analyzer_count=len(target.ids()),
            analyzer_ids=target.ids(),
            operation="register",
            error_type=type(exc).__name__,
            error_message=f"{type(exc).__name__} (message redacted)",
        )
        raise
    analyzer_ids = target.ids()
    log.info(
        "health_bootstrap_completed",
        run_key=None,
        repository_id=None,
        repo_id=None,
        phase="bootstrap",
        completed_phases=(),
        status="completed",
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        failure_kind=None,
        analyzer_ids=analyzer_ids,
        analyzer_count=len(analyzer_ids),
        added_count=len(set(analyzer_ids) - set(before_ids)),
        idempotent=analyzer_ids == before_ids,
        operation="register",
    )
    return target


register_all_health_adapters()

__all__ = [
    "ACTIVITY_POLICY_VERSION",
    "APPSEC_ADAPTER_VERSION",
    "APPSEC_ANALYZER_ID",
    "APPSEC_DEFINITION",
    "APPSEC_DIMENSION",
    "APPSEC_POLICY_REVISION",
    "APPSEC_SOURCE_COMMIT",
    "CICD_ANALYZER_ID",
    "CICD_DEFINITION",
    "CODE_HEALTH_ANALYZER_VERSION",
    "CODE_HEALTH_COLLECTOR_VERSION",
    "CRITICALITY_DEFINITION",
    "DEPENDENCY_ANALYZER_ID",
    "DEPENDENCY_DEFINITION",
    "FORGE_COMMUNITY_DEFINITION",
    "FORGE_METADATA_DEFINITION",
    "IDENTITY_ANALYZER_ID",
    "IDENTITY_DEFINITION",
    "ISSUES_ANALYZER_VERSION",
    "PYDRILLER_CONFIG_RELATIVE",
    "PYDRILLER_POLICY_REVISION",
    "PYDRILLER_SOURCE_COMMIT",
    "PYDRILLER_VALIDATED_VERSION",
    "QLTY_DEFINITION",
    "REPOHEALTH_DEFINITION",
    "REPOWISE_ANALYZER_ID",
    "REPOWISE_DEFINITION",
    "SCORECARD_DEFINITION",
    "SOKRATES_DEFINITION",
    "TEMPORAL_ANALYZER_ID",
    "TEMPORAL_DEFINITION",
    "VALE_ANALYZER_ID",
    "VALE_DEFINITION",
    "ActivityAnalyzer",
    "ActorClass",
    "AnalyzerContext",
    "AnalyzerDefinition",
    "AnalyzerRegistry",
    "AnalyzerResult",
    "AnalyzerStatus",
    "AppSecAnalyzer",
    "AppSecDataStatus",
    "AppSecFindingFact",
    "AppSecFacts",
    "CICDAnalyzer",
    "CICDDataStatus",
    "CICDFacts",
    "CICDPolicy",
    "CICDRetryRelation",
    "CICDRunFact",
    "CICDRunStatus",
    "CICDWindowFacts",
    "CachePolicy",
    "CodeHealthAnalyzer",
    "CodeHealthFacts",
    "CodeHealthFactsCollector",
    "CodeHealthPolicy",
    "CodeHealthSourcePorts",
    "CodeHealthStatus",
    "DependencyAdapter",
    "DependencyEdge",
    "DependencyFact",
    "EventNormalizer",
    "EvidenceRef",
    "FailureKind",
    "Finding",
    "FindingLocation",
    "ForgeAdapter",
    "GitActivityBaseline",
    "GitStructureFacts",
    "IdentityAdapter",
    "IdentityEvidence",
    "IdentityMatch",
    "IdentityResolver",
    "IssueCollectionFacts",
    "IssueEventFact",
    "IssueEventType",
    "IssueFact",
    "IssueMetricStatus",
    "IssueState",
    "IssuesAnalyzer",
    "IssuesPolicy",
    "Limitation",
    "MaterializedRollup",
    "Metric",
    "MetricValue",
    "NormalizedFact",
    "PlannedAnalyzer",
    "PyDrillerAdapter",
    "PyDrillerExecutionStatus",
    "PyDrillerFacts",
    "PyDrillerPolicy",
    "RefPolicy",
    "RepoWiseAdapter",
    "SonarFacts",
    "TemporalAdapter",
    "TemporalWindow",
    "TodoDebtFacts",
    "ValeAdapter",
    "SourceCraftAppSecAdapter",
    "SourceCraftAppSecHTTPTransport",
    "build_temporal_window",
    "appsec_adapter",
    "cicd_adapter",
    "classify_actor",
    "deduplicate_findings",
    "load_cicd_policy",
    "load_issues_policy",
    "materialized_rollups",
    "normalize_appsec_payload",
    "normalize_issue_inventory",
    "register_all_health_adapters",
    "register_appsec_adapter",
    "register_chaoss_adapters",
    "register_cicd_adapter",
    "register_dependency_adapters",
    "register_forge_adapters",
    "register_identity_adapters",
    "register_native_adapters",
    "register_repowise",
    "register_temporal_adapters",
    "register_vale_adapter",
    "registry",
    "vale_adapter",
]
