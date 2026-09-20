"""Health compatibility facade for neutral finding merge."""

from repowise.core.analysis.analyzer_integration.finding_merge import (
    deduplicate_findings,
    finding_identity,
)

__all__ = ["deduplicate_findings", "finding_identity"]
