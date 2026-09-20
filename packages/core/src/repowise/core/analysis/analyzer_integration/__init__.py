"""Neutral analyzer integration kernel.

This package intentionally has no import-time registration or product wiring.
Health adapters, scoring, persistence, and public projections belong to the
health edge and are supplied through the ports in this package.
"""

from __future__ import annotations

from .cache import AnalyzerCache, FileAnalyzerCache, cache_filename
from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    CachePolicy,
    ContractModel,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    Metric,
    MetricValue,
)
from .finding_merge import deduplicate_findings, finding_identity
from .lifecycle import (
    PHASES,
    AnalyzerOrchestrator,
    BatchOutcome,
    LifecycleOrchestrator,
    Orchestrator,
    RunOutcome,
    run_key,
)
from .ports import (
    CacheStore,
    CheckpointPort,
    CheckpointStore,
    Clock,
    CompositionPort,
    ContextCollector,
    ContextPort,
    PersistenceHook,
    PersistencePort,
    ProcessExecutor,
    ProcessPort,
    PublicationHook,
    PublicationPort,
    ScoreComposer,
)
from .process import (
    DEFAULT_OUTPUT_CAP,
    ENV_ALLOWLIST,
    Process,
    ProcessOutput,
    ProcessRequest,
    SubprocessProcess,
)
from .registry import AnalyzerFactory, AnalyzerRegistry, PlannedAnalyzer, registry
from .runner import AnalyzerRunner, cache_key, run, run_json_command
from .validation import ResultValidationError, validate_result

__all__ = [
    "DEFAULT_OUTPUT_CAP",
    "ENV_ALLOWLIST",
    "PHASES",
    "AnalyzerCache",
    "AnalyzerContext",
    "AnalyzerDefinition",
    "AnalyzerFactory",
    "AnalyzerOrchestrator",
    "AnalyzerRegistry",
    "AnalyzerResult",
    "AnalyzerRunner",
    "AnalyzerStatus",
    "BatchOutcome",
    "CachePolicy",
    "CacheStore",
    "CheckpointPort",
    "CheckpointStore",
    "Clock",
    "CompositionPort",
    "ContextCollector",
    "ContextPort",
    "ContractModel",
    "EvidenceRef",
    "FileAnalyzerCache",
    "Finding",
    "FindingLocation",
    "LifecycleOrchestrator",
    "Limitation",
    "Metric",
    "MetricValue",
    "Orchestrator",
    "PersistenceHook",
    "PersistencePort",
    "PlannedAnalyzer",
    "Process",
    "ProcessExecutor",
    "ProcessOutput",
    "ProcessPort",
    "ProcessRequest",
    "PublicationHook",
    "PublicationPort",
    "ResultValidationError",
    "RunOutcome",
    "ScoreComposer",
    "SubprocessProcess",
    "cache_filename",
    "cache_key",
    "deduplicate_findings",
    "finding_identity",
    "registry",
    "run",
    "run_json_command",
    "run_key",
    "validate_result",
]
