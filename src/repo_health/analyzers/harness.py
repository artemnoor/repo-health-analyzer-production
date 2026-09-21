"""Minimal serialized analyzer harness for local and worker execution."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from ..contracts.requests import canonical_json
from ..contracts.results import AnalyzerInput, CategoryResult


def execute_serialized(
    payload: str | bytes | Mapping[str, Any],
    factory: Callable[[AnalyzerInput], CategoryResult],
) -> str:
    """Validate JSON, execute one analyzer, and return only CategoryResult JSON."""

    decoded: object = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    analyzer_input = AnalyzerInput.model_validate(decoded)
    result = factory(analyzer_input)
    validated = CategoryResult.model_validate(result.model_dump(mode="json"))
    return canonical_json(validated)


__all__ = ["execute_serialized"]
