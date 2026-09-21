"""Activity facts view; only normalized Git facts are accepted."""

from ...contracts.results import GitFacts, RepositoryFacts


def view(facts: RepositoryFacts) -> GitFacts:
    return facts.git


__all__ = ["view"]
