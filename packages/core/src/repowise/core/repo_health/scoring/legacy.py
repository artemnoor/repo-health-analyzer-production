"""Explicit compatibility bridge for pre-contract health persistence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from repowise.core.analysis.health.composite import CompositeHealthScore, CompositeScoreConfig
from repowise.core.analysis.health.integrations.contracts import AnalyzerResult
from repowise.core.analysis.health.score_engine_v1 import compose_default_repo_health_score


class LegacyHealthScorePort(Protocol):
    """Compatibility-only composer for callers not yet on ScoreInput."""

    def score(
        self,
        results: Iterable[AnalyzerResult],
        config: CompositeScoreConfig | Mapping[str, object] | None = None,
        *,
        repository_id: str | None = None,
    ) -> CompositeHealthScore: ...


class DefaultLegacyHealthScorePort:
    """Keep the existing fallback policy in one named migration adapter."""

    def score(
        self,
        results: Iterable[AnalyzerResult],
        config: CompositeScoreConfig | Mapping[str, object] | None = None,
        *,
        repository_id: str | None = None,
    ) -> CompositeHealthScore:
        return compose_default_repo_health_score(results, config, repository_id=repository_id)


__all__ = ["DefaultLegacyHealthScorePort", "LegacyHealthScorePort"]
