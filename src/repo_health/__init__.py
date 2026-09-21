"""Standalone SourceCraft Repository Health Analyzer backend.

The package exposes only transport-neutral contracts at its root. API,
collection, analyzer, scoring and persistence modules are deliberately kept
behind explicit boundaries so the same business logic can run locally or in a
worker process.
"""

from .contracts import (
    CONTRACT_SCHEMA_VERSION,
    AnalysisRequest,
    CategoryResult,
    RepoHealthResult,
    RepositoryFacts,
    RepositoryRef,
)

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "AnalysisRequest",
    "CategoryResult",
    "RepoHealthResult",
    "RepositoryFacts",
    "RepositoryRef",
]
