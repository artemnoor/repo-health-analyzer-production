"""Transport-neutral persistence interfaces for Repo Health contracts."""

from __future__ import annotations

from typing import Protocol

from ..contracts.results import AnalysisEnvelope


class AnalysisEnvelopeConflictError(RuntimeError):
    """Raised when an idempotency key is reused for different content."""


class AnalysisEnvelopeWriter(Protocol):
    """Write an immutable analysis envelope exactly once."""

    async def write(
        self, envelope: AnalysisEnvelope, *, snapshot_id: str | None = None
    ) -> AnalysisEnvelope: ...


class AnalysisReadPort(Protocol):
    """Read stable contract DTOs without exposing ORM objects."""

    async def get(self, analysis_id: str) -> AnalysisEnvelope | None: ...

    async def get_by_idempotency(
        self, repository_id: str, idempotency_key: str
    ) -> AnalysisEnvelope | None: ...


__all__ = ["AnalysisEnvelopeConflictError", "AnalysisEnvelopeWriter", "AnalysisReadPort"]
