"""Source-independent collector ports.

The checkout path is intentionally present only in ``CollectionContext``. It
is an internal capability passed to a local collector and is never part of
``AnalysisRequest`` or ``RepositoryFacts`` serialization.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..contracts.requests import AnalysisRequest, RepositoryRef
from ..contracts.results import RepositoryFacts


class CollectionError(RuntimeError):
    """Typed collection failure; callers must publish a limitation, not zero."""


@dataclass(frozen=True, slots=True)
class CollectionLimits:
    max_files: int = 100_000
    max_commits: int = 50_000
    max_provider_pages: int = 100
    max_response_bytes: int = 10_000_000

    def __post_init__(self) -> None:
        if any(
            value <= 0
            for value in (
                self.max_files,
                self.max_commits,
                self.max_provider_pages,
                self.max_response_bytes,
            )
        ):
            raise ValueError("collection limits must be positive")


@dataclass(frozen=True, slots=True)
class CollectionContext:
    """Private capabilities for a local collection execution."""

    checkout_path: Path
    request: AnalysisRequest
    limits: CollectionLimits = field(default_factory=CollectionLimits)
    environment: Mapping[str, str] = field(default_factory=dict)


class CollectorPort(Protocol):
    """Port for local or provider-neutral normalized fact collection."""

    source_id: str

    def collect(
        self,
        repository: RepositoryRef,
        *,
        context: CollectionContext,
    ) -> RepositoryFacts | Awaitable[RepositoryFacts]: ...


class ProviderCollectorPort(CollectorPort, Protocol):
    """Port for a provider transport that emits only normalized facts."""

    provider: str


__all__ = [
    "CollectionContext",
    "CollectionError",
    "CollectionLimits",
    "CollectorPort",
    "ProviderCollectorPort",
]
