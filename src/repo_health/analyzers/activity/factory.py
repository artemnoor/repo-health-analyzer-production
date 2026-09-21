"""Activity analyzer boundary; PyDriller policy is injected by composition."""

from __future__ import annotations

from collections.abc import Callable

from ...contracts.results import AnalyzerInput, CategoryResult, HealthCategory
from .._boundary import AnalyzerEvaluator, ResultAdapter, bind_category_analyzer
from .analyzer import ActivityAnalyzer

ANALYZER_ID = "repo-health.activity"


def bind_activity_analyzer(
    evaluator: AnalyzerEvaluator,
    result_adapter: ResultAdapter,
) -> Callable[[AnalyzerInput], CategoryResult]:
    return bind_category_analyzer(
        category=HealthCategory.ACTIVITY,
        analyzer_id=ANALYZER_ID,
        evaluator=evaluator,
        result_adapter=result_adapter,
    )


def analyze(analyzer_input: AnalyzerInput) -> CategoryResult:
    return ActivityAnalyzer().analyze(analyzer_input)


__all__ = ["ANALYZER_ID", "ActivityAnalyzer", "analyze", "bind_activity_analyzer"]
