"""Application orchestration over the six independent analyzer task boundaries."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

from .analyzers.registry import AnalyzerSpec, canonical_registry
from .contracts.requests import AnalysisRequest
from .contracts.results import (
    AnalysisState,
    AnalysisStatus,
    CategoryResult,
    RepositoryFacts,
)
from .execution import AnalyzerTask, LocalExecutor, ResourceLimits


def _policy_digest(policy: str) -> str:
    return hashlib.sha256(policy.encode("utf-8")).hexdigest()


class RepoHealthAnalysisRun:
    """Typed orchestration result without persistence or API dependencies."""

    def __init__(
        self,
        *,
        status: AnalysisStatus,
        category_results: tuple[CategoryResult, ...],
        tasks: tuple[AnalyzerTask, ...],
    ) -> None:
        self.status = status
        self.category_results = category_results
        self.tasks = tasks


class RepoHealthOrchestrator:
    """Create deterministic tasks and isolate analyzer failures with gather."""

    def __init__(
        self,
        executor: LocalExecutor,
        *,
        resource_limits: ResourceLimits | None = None,
    ) -> None:
        self._executor = executor
        self._resource_limits = resource_limits or ResourceLimits()

    async def analyze(
        self,
        request: AnalysisRequest,
        facts: RepositoryFacts,
        *,
        analyzer_ids: tuple[str, ...] | None = None,
    ) -> RepoHealthAnalysisRun:
        repository = request.repository
        if facts.repository is not None and facts.repository.repository_id != repository.repository_id:
            raise ValueError("analysis request and facts identify different repositories")
        requested = analyzer_ids or request.requested_analyzer_ids or canonical_registry.ids()
        specs: list[AnalyzerSpec] = []
        for analyzer_id in sorted(set(requested)):
            entry = canonical_registry.get(analyzer_id)
            if entry is None:
                raise ValueError(f"unknown canonical analyzer: {analyzer_id}")
            specs.append(entry[0])
        facts_digest = facts.digest()
        tasks = tuple(
            AnalyzerTask(
                analysis_id=request.analysis_id,
                analyzer_id=spec.id,
                analyzer_version=spec.version,
                category=spec.category,
                input={
                    "analysis_id": request.analysis_id,
                    "repository": repository,
                    "analyzer_id": spec.id,
                    "analyzer_version": spec.version,
                    "facts": facts,
                    "facts_digest": facts_digest,
                    "policy_digest": _policy_digest(spec.policy),
                    "deadline_at": request.deadline_at,
                },
                facts_digest=facts_digest,
                policy_digest=_policy_digest(spec.policy),
                deadline_at=request.deadline_at,
                resource_limits=self._resource_limits,
            )
            for spec in specs
        )
        outcomes = await asyncio.gather(
            *(self._executor.execute(task) for task in tasks), return_exceptions=False
        )
        results = tuple(outcome.result for outcome in outcomes)
        completed = tuple(
            result.analyzer_id for result in results if result.status.value != "error"
        )
        failed = tuple(result.analyzer_id for result in results if result.status.value == "error")
        if failed and completed:
            state = AnalysisState.PARTIAL
        elif failed:
            state = AnalysisState.FAILED
        else:
            state = AnalysisState.COMPLETED
        now = datetime.now(UTC)
        status = AnalysisStatus(
            analysis_id=request.analysis_id,
            state=state,
            completed_analyzer_ids=completed,
            failed_analyzer_ids=failed,
            started_at=now,
            finished_at=now,
        )
        return RepoHealthAnalysisRun(status=status, category_results=results, tasks=tasks)


__all__ = ["RepoHealthAnalysisRun", "RepoHealthOrchestrator"]
