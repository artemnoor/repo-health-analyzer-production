"""Canonical six-category analyzer ownership boundary.

This package is intentionally side-effect free. Application composition roots
register executable factories explicitly; importing one analyzer cannot import
or register unrelated analyzers.
"""

from .registry import (
    CANONICAL_ANALYZER_IDS,
    OWNERSHIP_MANIFEST,
    AnalyzerFactory,
    AnalyzerOwnership,
    AnalyzerSpec,
    CanonicalAnalyzerRegistry,
    RegistryResolution,
    canonical_registry,
    resolve_analyzer_id,
)

__all__ = [
    "CANONICAL_ANALYZER_IDS",
    "OWNERSHIP_MANIFEST",
    "AnalyzerFactory",
    "AnalyzerOwnership",
    "AnalyzerSpec",
    "CanonicalAnalyzerRegistry",
    "RegistryResolution",
    "canonical_registry",
    "resolve_analyzer_id",
]
