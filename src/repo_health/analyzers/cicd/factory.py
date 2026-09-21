"""CI/CD analyzer boundary; SourceCraft CI policy is injected by composition."""

from __future__ import annotations

from collections.abc import Callable

from ...contracts.results import AnalyzerInput, CategoryResult, HealthCategory
from .._boundary import AnalyzerEvaluator, ResultAdapter, bind_category_analyzer
from .analyzer import CicdAnalyzer

ANALYZER_ID = "repo-health.cicd"


def bind_cicd_analyzer(
    evaluator: AnalyzerEvaluator,
    result_adapter: ResultAdapter,
) -> Callable[[AnalyzerInput], CategoryResult]:
    return bind_category_analyzer(
        category=HealthCategory.CICD,
        analyzer_id=ANALYZER_ID,
        evaluator=evaluator,
        result_adapter=result_adapter,
    )


def analyze(analyzer_input: AnalyzerInput) -> CategoryResult:
    return CicdAnalyzer().analyze(analyzer_input)


__all__ = ["ANALYZER_ID", "CicdAnalyzer", "analyze", "bind_cicd_analyzer"]
