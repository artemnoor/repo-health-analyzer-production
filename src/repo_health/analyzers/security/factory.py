"""Security analyzer boundary; SourceCraft AppSec policy is injected."""

from __future__ import annotations

from collections.abc import Callable

from ...contracts.results import AnalyzerInput, CategoryResult, HealthCategory
from .._boundary import AnalyzerEvaluator, ResultAdapter, bind_category_analyzer
from .analyzer import SecurityAnalyzer

ANALYZER_ID = "repo-health.security"


def bind_security_analyzer(
    evaluator: AnalyzerEvaluator,
    result_adapter: ResultAdapter,
) -> Callable[[AnalyzerInput], CategoryResult]:
    return bind_category_analyzer(
        category=HealthCategory.SECURITY,
        analyzer_id=ANALYZER_ID,
        evaluator=evaluator,
        result_adapter=result_adapter,
    )


def analyze(analyzer_input: AnalyzerInput) -> CategoryResult:
    return SecurityAnalyzer().analyze(analyzer_input)


__all__ = ["ANALYZER_ID", "SecurityAnalyzer", "analyze", "bind_security_analyzer"]
