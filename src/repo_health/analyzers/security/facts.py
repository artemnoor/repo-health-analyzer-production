"""Security facts view; AppSec REST normalization is upstream."""

from ...contracts.results import RepositoryFacts, SecurityFacts


def view(facts: RepositoryFacts) -> SecurityFacts:
    return facts.security


__all__ = ["view"]
