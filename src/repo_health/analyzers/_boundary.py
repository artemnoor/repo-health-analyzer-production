"""Common process/service boundary for independently deployable analyzers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..contracts.results import AnalyzerInput, CategoryResult, HealthCategory


class AnalyzerEvaluator(Protocol):
    def __call__(self, analyzer_input: AnalyzerInput) -> Any: ...


class ResultAdapter(Protocol):
    def __call__(
        self,
        result: Any,
        *,
        analysis_id: str,
        category: HealthCategory,
    ) -> CategoryResult: ...


def bind_category_analyzer(
    *,
    category: HealthCategory,
    analyzer_id: str,
    evaluator: AnalyzerEvaluator,
    result_adapter: ResultAdapter,
) -> Callable[[AnalyzerInput], CategoryResult]:
    """Bind existing policy/evidence logic to a transport-neutral analyzer port.

    ``evaluator`` is injected by the composition root. This package therefore
    owns the boundary and result category, but never imports a provider, API,
    persistence layer, or another analyzer's implementation.
    """

    def analyze(analyzer_input: AnalyzerInput) -> CategoryResult:
        if analyzer_input.analyzer_id != analyzer_id:
            raise ValueError(f"AnalyzerInput ID {analyzer_input.analyzer_id!r} does not match {analyzer_id!r}")
        result = result_adapter(
            evaluator(analyzer_input),
            analysis_id=analyzer_input.analysis_id,
            category=category,
        )
        if result.category is not category:
            raise ValueError(f"result adapter returned wrong category for {analyzer_id}")
        if result.analyzer_id != analyzer_id:
            raise ValueError(f"result adapter returned wrong analyzer for {analyzer_id}")
        return result

    return analyze


__all__ = ["AnalyzerEvaluator", "ResultAdapter", "bind_category_analyzer"]
