"""CI/CD facts view; only normalized provider facts are accepted."""

from ...contracts.results import CicdFacts, RepositoryFacts


def view(facts: RepositoryFacts) -> CicdFacts:
    return facts.cicd


__all__ = ["view"]
