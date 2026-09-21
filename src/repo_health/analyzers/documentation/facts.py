"""Documentation facts view; no provider or analyzer imports."""

from ...contracts.results import DocumentationFacts, RepositoryFacts


def view(facts: RepositoryFacts) -> DocumentationFacts:
    return facts.documentation


__all__ = ["view"]
