"""Deterministic collection orchestration for normalized RepositoryFacts."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog

from ..contracts.requests import AnalysisRequest
from ..contracts.results import CollectionState, Limitation, RepositoryFacts, SourceStatus
from .ports import CollectionContext, CollectionLimits, CollectorPort

log = structlog.get_logger("repo_health.collection.service")


class CollectionService:
    """Collect independent sources and preserve partial/unavailable states."""

    def __init__(
        self,
        collectors: Sequence[CollectorPort],
        *,
        limits: CollectionLimits | None = None,
    ) -> None:
        if not collectors:
            raise ValueError("CollectionService requires at least one collector")
        self.collectors = tuple(sorted(collectors, key=lambda item: item.source_id))
        self.limits = limits or CollectionLimits()

    async def collect(self, request: AnalysisRequest, *, checkout_path) -> RepositoryFacts:
        context = CollectionContext(checkout_path=checkout_path, request=request, limits=self.limits)
        facts = RepositoryFacts(repository=request.repository, collected_at=datetime.now(UTC))
        log.info(
            "collection_started",
            analysis_id=request.analysis_id,
            repository_id=request.repository.repository_id,
            collector_count=len(self.collectors),
        )
        for collector in self.collectors:
            try:
                result = collector.collect(request.repository, context=context)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, RepositoryFacts):
                    raise TypeError(f"collector {collector.source_id} returned an invalid facts object")
                facts = self._merge(facts, result)
                log.info("collector_finished", analysis_id=request.analysis_id, source_id=collector.source_id)
            except Exception as exc:
                limitation = Limitation(
                    code=f"{collector.source_id}.collection_failed",
                    reason="collector failed; category remains explicitly unavailable",
                )
                facts = facts.model_copy(
                    update={
                        "source_statuses": (
                            *facts.source_statuses,
                            SourceStatus(
                                source_id=collector.source_id,
                                state=CollectionState.ERROR,
                                collected_at=datetime.now(UTC),
                                limitations=(limitation,),
                            ),
                        ),
                        "limitations": (*facts.limitations, limitation),
                    }
                )
                log.warning(
                    "collector_failed",
                    analysis_id=request.analysis_id,
                    source_id=collector.source_id,
                    error_type=type(exc).__name__,
                )
        log.info(
            "collection_finished",
            analysis_id=request.analysis_id,
            facts_digest=facts.digest(),
            source_count=len(facts.source_statuses),
        )
        return facts

    @staticmethod
    def _merge(left: RepositoryFacts, right: RepositoryFacts) -> RepositoryFacts:
        updates = {
            "repository": right.repository or left.repository,
            "collected_at": right.collected_at or left.collected_at,
            "source_versions": {**left.source_versions, **right.source_versions},
            "source_statuses": (*left.source_statuses, *right.source_statuses),
            "capabilities": (*left.capabilities, *right.capabilities),
            "limitations": (*left.limitations, *right.limitations),
        }
        for group in ("git", "documentation", "issues", "cicd", "security", "code_health"):
            value = getattr(right, group)
            if value.available or value.observations or value.limitations:
                updates[group] = value
        return left.model_copy(update=updates)


__all__ = ["CollectionService"]
