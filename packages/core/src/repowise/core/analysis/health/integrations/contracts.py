"""Compatibility exports for the neutral analyzer integration contracts.

The health import path remains supported while the models have a single
canonical definition in the neutral kernel.
"""

from repowise.core.analysis.analyzer_integration.contracts import (
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
