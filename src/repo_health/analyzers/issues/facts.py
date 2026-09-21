"""Issues facts view; SourceCraft payloads are not visible here."""

from ...contracts.results import IssuesFacts, RepositoryFacts


def view(facts: RepositoryFacts) -> IssuesFacts:
    return facts.issues


__all__ = ["view"]
