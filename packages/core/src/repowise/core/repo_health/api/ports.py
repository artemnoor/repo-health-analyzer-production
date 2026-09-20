"""Inbound application ports used by REST, MCP and CLI adapters."""

from __future__ import annotations

from typing import Protocol

from ..contracts.requests import AnalysisRequest
from ..contracts.results import AnalysisStatus, RepoHealthResult


class AnalysisOrchestratorPort(Protocol):
    """Submit and inspect analyses without exposing an executor or ORM."""

    async def submit(self, request: AnalysisRequest) -> AnalysisStatus: ...

    async def status(self, analysis_id: str) -> AnalysisStatus | None: ...

    async def result(self, analysis_id: str) -> RepoHealthResult | None: ...


__all__ = ["AnalysisOrchestratorPort"]
