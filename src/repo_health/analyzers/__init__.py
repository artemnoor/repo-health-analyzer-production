"""Canonical six-category analyzer boundary.

This package is intentionally side-effect free. Application composition roots
register executable factories explicitly; importing one analyzer cannot import
or register unrelated analyzers.
"""

from .registry import (
    CANONICAL_ANALYZER_IDS,
    AnalyzerFactory,
    AnalyzerSpec,
    CanonicalAnalyzerRegistry,
    canonical_registry,
    register_default_factories,
)

__all__ = [
    "CANONICAL_ANALYZER_IDS",
    "AnalyzerFactory",
    "AnalyzerSpec",
    "CanonicalAnalyzerRegistry",
    "canonical_registry",
    "register_default_factories",
]
