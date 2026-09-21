"""Explicit unavailable collectors used for optional production dependencies."""

from __future__ import annotations

from datetime import UTC, datetime

from ..contracts.requests import RepositoryRef
from ..contracts.results import (
    CicdFacts,
    CodeHealthFacts,
    CollectionState,
    DocumentationFacts,
    FactGroup,
    GitFacts,
    IssuesFacts,
    Limitation,
    RepositoryFacts,
    SecurityFacts,
    SourceStatus,
)
from .ports import CollectionContext

_GROUPS: dict[str, type[FactGroup]] = {
    "git": GitFacts,
    "documentation": DocumentationFacts,
    "issues": IssuesFacts,
    "cicd": CicdFacts,
    "security": SecurityFacts,
    "code_health": CodeHealthFacts,
}


class UnavailableFactCollector:
    """Produce an explicit empty group without inventing measurements."""

    def __init__(self, *, source_id: str, fact_group: str, reason: str, state: CollectionState) -> None:
        if fact_group not in _GROUPS:
            raise ValueError(f"unsupported normalized fact group: {fact_group}")
        self.source_id = source_id
        self.fact_group = fact_group
        self.reason = reason[:512]
        self.state = state

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        del context
        limitation = Limitation(code=f"{self.source_id}.unavailable", reason=self.reason)
        group = _GROUPS[self.fact_group](limitations=(limitation,))
        status = SourceStatus(
            source_id=self.source_id,
            state=self.state,
            collected_at=datetime.now(UTC),
            limitations=(limitation,),
        )
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: "unavailable"},
            source_statuses=(status,),
            limitations=(limitation,),
            **{self.fact_group: group},
        )


__all__ = ["UnavailableFactCollector"]
