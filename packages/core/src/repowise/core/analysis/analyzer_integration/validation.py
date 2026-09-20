"""The single boundary where analyzer output becomes a trusted result."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from .contracts import AnalyzerDefinition, AnalyzerResult


class ResultValidationError(ValueError):
    """Raised when a factory output is not a valid result for its definition."""

    def __init__(self, message: str, *, error_type: str = "validation") -> None:
        super().__init__(message)
        self.error_type = error_type


def validate_result(raw: object, definition: AnalyzerDefinition) -> AnalyzerResult:
    try:
        if isinstance(raw, AnalyzerResult):
            result = AnalyzerResult.model_validate(raw.model_dump())
        elif isinstance(raw, Mapping):
            result = AnalyzerResult.model_validate(raw)
        else:
            raise ResultValidationError(
                f"factory returned {type(raw).__name__}, expected AnalyzerResult or mapping",
                error_type="type",
            )
    except ValidationError as exc:
        raise ResultValidationError(
            "factory returned an invalid analyzer result", error_type="validation"
        ) from exc
    if result.analyzer_id != definition.id:
        raise ResultValidationError(
            f"result analyzer_id {result.analyzer_id!r} does not match {definition.id!r}",
            error_type="identity",
        )
    return result


__all__ = ["ResultValidationError", "validate_result"]
