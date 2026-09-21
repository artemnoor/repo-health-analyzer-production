"""Canonical collection → analyzer tasks → Score v1 lifecycle."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import structlog

from ..analyzers import CANONICAL_ANALYZER_IDS, canonical_registry, register_default_factories
from ..collection.service import CollectionService
from ..contracts.execution import AnalyzerTask, ExecutionOutcome
from ..contracts.requests import AnalysisRequest
from ..contracts.results import (
    AnalysisEnvelope,
    AnalysisState,
    AnalysisStatus,
    CategoryResult,
    HealthCategory,
    Limitation,
    RepoHealthResult,
    RepositoryFacts,
    ScoreInput,
)
from ..execution.local import LocalExecutor, failure_result
from ..persistence.ports import PersistencePort
from ..scoring.v1 import ScoreEngineV1

log = structlog.get_logger("repo_health.orchestration")


class ExecutorPort(Protocol):
    async def execute_many(self, tasks: Sequence[AnalyzerTask]) -> tuple[ExecutionOutcome, ...]: ...


class AnalysisOrchestrator:
    """One lifecycle with pluggable collection, execution and persistence."""

    def __init__(
        self,
        *,
        collection: CollectionService,
        persistence: PersistencePort,
        executor: ExecutorPort | None = None,
        score_engine: ScoreEngineV1 | None = None,
    ) -> None:
        self.collection = collection
        self.persistence = persistence
        register_default_factories()
        factories = {analyzer_id: canonical_registry.get(analyzer_id)[1] for analyzer_id in CANONICAL_ANALYZER_IDS}  # type: ignore[index]
        self.executor = executor or LocalExecutor({key: value for key, value in factories.items() if value is not None})
        self.score_engine = score_engine or ScoreEngineV1()

    def start(self, request: AnalysisRequest):
        self._validate_requested(request)
        return self.persistence.create_analysis(request)

    async def analyze(self, request: AnalysisRequest, *, checkout_path: str | Path) -> AnalysisEnvelope:
        self._validate_requested(request)
        record = self.persistence.create_analysis(request)
        if record.envelope.score is not None:
            return record.envelope
        started = datetime.now(UTC)
        policy_digest = request.policy_digest or hashlib.sha256(b"repo-health-policy-v1").hexdigest()
        try:
            facts = await self.collection.collect(request, checkout_path=Path(checkout_path))
        except Exception as exc:
            facts = RepositoryFacts(
                repository=request.repository,
                limitations=(
                    Limitation(code="collection.failed", reason="collection failed before analyzer dispatch"),
                ),
            )
            categories = tuple(
                item
                for item in (
                    failure_result(task, reason="collection failed before analyzer dispatch", kind="collection_error")
                    for task in self._tasks(request, facts, policy_digest)
                )
            )
            return self._commit_result(
                record, request, facts, categories, policy_digest, started, failure_reason=type(exc).__name__
            )

        tasks = self._tasks(request, facts, policy_digest)
        try:
            outcomes = await self.executor.execute_many(tasks)
            categories = tuple(sorted((outcome.result for outcome in outcomes), key=lambda item: item.analyzer_id))
            failure_reason = None
        except Exception as exc:
            categories = tuple(
                item
                for item in (
                    failure_result(
                        task, reason="executor failed before task results were returned", kind="executor_error"
                    )
                    for task in tasks
                )
            )
            failure_reason = type(exc).__name__
        return self._commit_result(
            record, request, facts, categories, policy_digest, started, failure_reason=failure_reason
        )

    def _commit_result(
        self,
        record,
        request: AnalysisRequest,
        facts: RepositoryFacts,
        categories: tuple[CategoryResult, ...],
        policy_digest: str,
        started: datetime,
        *,
        failure_reason: str | None,
    ) -> AnalysisEnvelope:
        score = self.score_engine.score(self._score_input(request, categories, policy_digest))
        failed = tuple(item.analyzer_id for item in categories if item.status.value in {"error", "skipped"})
        omitted = len(categories) != len(CANONICAL_ANALYZER_IDS)
        state = (
            AnalysisState.FAILED
            if failure_reason
            else AnalysisState.PARTIAL
            if failed or omitted
            else AnalysisState.COMPLETED
        )
        reason = failure_reason or (
            "one or more analyzer categories were unavailable"
            if failed
            else "requested analyzer subset omitted categories"
            if omitted
            else None
        )
        finished = datetime.now(UTC)
        status = AnalysisStatus(
            analysis_id=request.analysis_id,
            state=state,
            completed_analyzer_ids=tuple(
                item.analyzer_id for item in categories if item.status.value not in {"error", "skipped"}
            ),
            failed_analyzer_ids=failed or (CANONICAL_ANALYZER_IDS if failure_reason else ()),
            started_at=started,
            finished_at=finished,
            reason=reason,
        )
        envelope = AnalysisEnvelope(
            analysis_id=request.analysis_id,
            request=request,
            facts=facts,
            facts_digest=facts.digest(),
            category_results=categories,
            score=score,
            status=status,
            idempotency_key=record.idempotency_key,
            policy_digest=policy_digest,
            tool_versions=facts.source_versions,
            created_at=record.created_at,
            started_at=started,
            finished_at=finished,
        )
        self.persistence.commit_envelope(envelope)
        log.info(
            "analysis_finished",
            analysis_id=request.analysis_id,
            repository_id=request.repository.repository_id,
            state=state.value,
            score=score.overall_score,
            category_count=len(categories),
        )
        return envelope

    @staticmethod
    def _validate_requested(request: AnalysisRequest) -> None:
        requested = tuple(request.requested_analyzer_ids) or CANONICAL_ANALYZER_IDS
        unknown = sorted(set(requested) - set(CANONICAL_ANALYZER_IDS))
        if unknown:
            raise ValueError(f"unknown canonical analyzers: {unknown}")

    @staticmethod
    def _tasks(request: AnalysisRequest, facts: RepositoryFacts, policy_digest: str) -> tuple[AnalyzerTask, ...]:
        requested = tuple(request.requested_analyzer_ids) or CANONICAL_ANALYZER_IDS
        facts_digest = facts.digest()
        return tuple(
            AnalyzerTask(
                analysis_id=request.analysis_id,
                analyzer_id=analyzer_id,
                analyzer_version=canonical_registry.get(analyzer_id)[0].version,
                category=canonical_registry.get(analyzer_id)[0].category,
                input={
                    "analysis_id": request.analysis_id,
                    "repository": request.repository.model_dump(mode="json"),
                    "analyzer_id": analyzer_id,
                    "analyzer_version": canonical_registry.get(analyzer_id)[0].version,
                    "facts": facts.model_dump(mode="json"),
                    "facts_digest": facts_digest,
                    "policy_digest": policy_digest,
                },
                facts_digest=facts_digest,
                policy_digest=policy_digest,
                deadline_at=request.deadline_at,
            )
            for analyzer_id in requested
        )

    def get_status(self, analysis_id: str):
        record = self.persistence.get_analysis(analysis_id)
        return None if record is None else record.envelope.status

    def get_result(self, analysis_id: str) -> RepoHealthResult | None:
        record = self.persistence.get_analysis(analysis_id)
        return None if record is None else record.envelope.score

    @staticmethod
    def _score_input(
        request: AnalysisRequest, categories: tuple[CategoryResult, ...], policy_digest: str
    ) -> ScoreInput:
        by_category = {item.category: item for item in categories}
        return ScoreInput(
            analysis_id=request.analysis_id,
            repository=request.repository,
            documentation=by_category.get(HealthCategory.DOCUMENTATION),
            activity=by_category.get(HealthCategory.ACTIVITY),
            issues=by_category.get(HealthCategory.ISSUES),
            cicd=by_category.get(HealthCategory.CICD),
            security=by_category.get(HealthCategory.SECURITY),
            code_health=by_category.get(HealthCategory.CODE_HEALTH),
            score_engine_version="repo-health-score-v1",
            policy_digest=policy_digest,
        )


__all__ = ["AnalysisOrchestrator"]
