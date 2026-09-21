"""Code Health facts view; SonarQube/git-sizer/TODO are upstream tools."""

from ...contracts.results import CodeHealthFacts, RepositoryFacts


def view(facts: RepositoryFacts) -> CodeHealthFacts:
    return facts.code_health


__all__ = ["view"]
