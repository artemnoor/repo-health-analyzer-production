"""Compatibility helpers shared by the Issues analyzer tests."""

from __future__ import annotations

import importlib
import sys

_COVERAGE_MODULE = "repowise.core.analysis.health.coverage"
_COVERAGE_PARENT = "repowise.core.analysis.health"
MISSING = object()


def install_preexisting_coverage_shim() -> tuple[object, object, object]:
    previous_module = sys.modules.get(_COVERAGE_MODULE, MISSING)
    previous_parent = sys.modules.get(_COVERAGE_PARENT, MISSING)
    previous_parent_attr = (
        getattr(previous_parent, "coverage", MISSING)
        if previous_parent is not MISSING
        else MISSING
    )
    if previous_module is MISSING:
        importlib.import_module(_COVERAGE_MODULE)
    return previous_module, previous_parent, previous_parent_attr


def restore_preexisting_coverage_shim(previous: tuple[object, object, object]) -> None:
    previous_module, _previous_parent, previous_parent_attr = previous
    if previous_module is MISSING:
        importlib.import_module(_COVERAGE_MODULE)
    else:
        sys.modules[_COVERAGE_MODULE] = previous_module  # type: ignore[assignment]
    parent = sys.modules.get(_COVERAGE_PARENT)
    if parent is not None:
        if previous_parent_attr is MISSING:
            vars(parent).pop("coverage", None)
        else:
            parent.coverage = previous_parent_attr
