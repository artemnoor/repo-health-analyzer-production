"""Deterministic collection orchestration for normalized RepositoryFacts."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog

from ..contracts.requests import AnalysisRequest, AssessmentProfile
from ..contracts.results import (
    CapabilityStatus,
    CicdFacts,
    CodeHealthFacts,
    CollectionState,
    DocumentationFacts,
    GitFacts,
    IssuesFacts,
    Limitation,
    ProviderCapabilityState,
    RepositoryFacts,
    SecurityFacts,
    SourceStatus,
)
from .merge import merge_repository_facts
from .ports import CollectionContext, CollectionLimits, CollectorPort

log = structlog.get_logger("repo_health.collection.service")


class CollectionService:
    """Collect independent sources and preserve partial/unavailable states."""

    def __init__(
        self,
        collectors: Sequence[CollectorPort],
        *,
        limits: CollectionLimits | None = None,
        capability_states: Sequence[CapabilityStatus] = (),
    ) -> None:
        if not collectors:
            raise ValueError("CollectionService requires at least one collector")
        self.collectors = tuple(sorted(collectors, key=lambda item: item.source_id))
        self.limits = limits or CollectionLimits()
        self.capability_states = tuple(sorted(capability_states, key=lambda item: item.capability_id))

    async def collect(self, request: AnalysisRequest, *, checkout_path) -> RepositoryFacts:
        context = CollectionContext(checkout_path=checkout_path, request=request, limits=self.limits)
        facts = RepositoryFacts(
            repository=request.repository,
            assessment_profile=request.assessment_profile,
            capability_states=self._capabilities_for(request),
            collected_at=datetime.now(UTC),
        )
        log.info(
            "collection_started",
            analysis_id=request.analysis_id,
            repository_id=request.repository.repository_id,
            collector_count=len(self.collectors),
        )
        for collector in self.collectors:
            try:
                result = (
                    self._profile_excluded(request, collector)
                    if self._is_owner_source(collector) and request.assessment_profile is AssessmentProfile.PUBLIC
                    else collector.collect(request.repository, context=context)
                )
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
        return facts.model_copy(
            update={
                "assessment_profile": request.assessment_profile,
                "capability_states": self._capabilities_for(request),
                "used_sources": tuple(
                    sorted(
                        (set(facts.used_sources) | {status.source_id for status in facts.source_statuses})
                        - {
                            status.source_id
                            for status in facts.source_statuses
                            if any(item.code == "assessment.public_sourcecraft_excluded" for item in status.limitations)
                        }
                    )
                ),
            }
        )

    def _capabilities_for(self, request: AnalysisRequest) -> tuple[CapabilityStatus, ...]:
        states = {item.capability_id: item for item in self.capability_states}
        if request.assessment_profile is AssessmentProfile.PUBLIC:
            states["sourcecraft"] = CapabilityStatus(
                capability_id="sourcecraft",
                state=ProviderCapabilityState.UNAVAILABLE,
                reason="owner-authorized SourceCraft data is excluded from PUBLIC assessment",
            )
        return tuple(sorted(states.values(), key=lambda item: item.capability_id))

    @staticmethod
    def _is_owner_source(collector: CollectorPort) -> bool:
        return getattr(collector, "provider", None) == "sourcecraft"

    @staticmethod
    def _profile_excluded(request: AnalysisRequest, collector: CollectorPort) -> RepositoryFacts:
        groups = {
            "documentation": DocumentationFacts,
            "git": GitFacts,
            "issues": IssuesFacts,
            "cicd": CicdFacts,
            "security": SecurityFacts,
            "code_health": CodeHealthFacts,
        }
        fact_group = getattr(collector, "fact_group", None)
        if fact_group not in groups:
            raise ValueError(f"owner source {collector.source_id} has no normalized fact group")
        limitation = Limitation(
            code="assessment.public_sourcecraft_excluded",
            reason="owner-authorized SourceCraft data is not part of PUBLIC assessment",
            affected_scope=fact_group,
        )
        status = SourceStatus(
            source_id=collector.source_id,
            state=CollectionState.UNAVAILABLE,
            source_version="profile-excluded",
            collected_at=datetime.now(UTC),
            limitations=(limitation,),
        )
        return RepositoryFacts(
            repository=request.repository,
            assessment_profile=request.assessment_profile,
            source_versions={collector.source_id: "profile-excluded"},
            source_statuses=(status,),
            limitations=(limitation,),
            **{fact_group: groups[fact_group](limitations=(limitation,))},
        )

    @staticmethod
    def _merge(left: RepositoryFacts, right: RepositoryFacts) -> RepositoryFacts:
        return merge_repository_facts(left, right)


__all__ = ["CollectionService"]
