"""Code Health analyzer boundary; external engines stay behind collectors."""

from __future__ import annotations

from collections.abc import Callable

from ...contracts.results import AnalyzerInput, CategoryResult, HealthCategory
from .._boundary import AnalyzerEvaluator, ResultAdapter, bind_category_analyzer

ANALYZER_ID = "repo-health.code-health"


def bind_code_health_analyzer(
    evaluator: AnalyzerEvaluator,
    result_adapter: ResultAdapter,
) -> Callable[[AnalyzerInput], CategoryResult]:
    return bind_category_analyzer(
        category=HealthCategory.CODE_HEALTH,
        analyzer_id=ANALYZER_ID,
        evaluator=evaluator,
        result_adapter=result_adapter,
    )


__all__ = ["ANALYZER_ID", "bind_code_health_analyzer"]
