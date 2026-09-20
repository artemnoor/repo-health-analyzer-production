"""ScorePort adapter for the existing frozen Repo Health Score v1 engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from repowise.core.analysis.health.score_engine_v1 import compose_repo_health_score_v1

from ..contracts.adapters import category_result_to_analyzer_result
from ..contracts.results import (
    AnalysisState,
    AnalysisStatus,
    Limitation,
    RepoHealthResult,
    ScoreInput,
)


class ScorePort(Protocol):
    def score(self, score_input: ScoreInput) -> RepoHealthResult: ...


class FrozenRepoHealthScorePort:
    """Compose one canonical six-slot input through the existing v1 engine."""

    def score(self, score_input: ScoreInput) -> RepoHealthResult:
        categories = (
            score_input.documentation,
            score_input.activity,
            score_input.issues,
            score_input.cicd,
            score_input.security,
            score_input.code_health,
        )
        legacy_results = tuple(
            category_result_to_analyzer_result(category)
            for category in categories
            if category is not None
        )
        weights = score_input.weights if isinstance(score_input.weights, Mapping) else None
        score = compose_repo_health_score_v1(legacy_results, weights=weights)
        completed = tuple(category.analyzer_id for category in categories if category is not None)
        status = AnalysisStatus(
            analysis_id=score_input.analysis_id,
            state=AnalysisState.COMPLETED,
            completed_analyzer_ids=completed,
        )
        limitations = tuple(
            Limitation(
                code=item.kind,
                reason=item.reason,
                affected_scope=item.affected_scope,
            )
            for item in score.limitations
        )
        return RepoHealthResult(
            analysis_id=score_input.analysis_id,
            repository=score_input.repository,
            status=status,
            overall_score=score.overall,
            score_before_caps=score.score_before_cap,
            score_engine_version=score.version,
            policy_digest=score_input.policy_digest,
            score_config_digest=score.score_config_digest,
            presentation_state=score.presentation_state,
            coverage=score.coverage,
            confidence=score.confidence,
            evidence_coverage=score.evidence_coverage,
            coverage_k=score.coverage_k,
            applied_caps=score.applied_caps,
            limitations=limitations,
            score_status=score.status.value,
            documentation=score_input.documentation,
            activity=score_input.activity,
            issues=score_input.issues,
            cicd=score_input.cicd,
            security=score_input.security,
            code_health=score_input.code_health,
        )


__all__ = ["FrozenRepoHealthScorePort", "ScorePort"]
