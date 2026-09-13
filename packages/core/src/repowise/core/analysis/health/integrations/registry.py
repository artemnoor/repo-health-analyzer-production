"""Deterministic analyzer registration and capability planning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog

from .contracts import AnalyzerContext, AnalyzerDefinition, AnalyzerResult

log = structlog.get_logger("health.registry")
AnalyzerFactory = Callable[[AnalyzerContext], AnalyzerResult]


@dataclass(frozen=True)
class PlannedAnalyzer:
    definition: AnalyzerDefinition
    factory: AnalyzerFactory
    missing_capabilities: tuple[str, ...] = ()
    disabled_reason: str | None = None

    @property
    def ready(self) -> bool:
        return not self.missing_capabilities and self.disabled_reason is None


def _missing_capabilities(definition: AnalyzerDefinition, context: AnalyzerContext) -> tuple[str, ...]:
    available = set(context.capabilities)
    missing = [requirement for requirement in definition.requires if requirement not in available]
    supported = context.inventory.get("languages")
    if definition.supports and supported:
        languages = {str(language) for language in supported}
        if not languages.intersection(definition.supports):
            missing.append(f"unsupported:{','.join(definition.supports)}")
    return tuple(sorted(set(missing)))


class AnalyzerRegistry:
    """Own analyzer identity, validation, capability filtering and ordering."""

    def __init__(self, *, allow_experimental: bool = False) -> None:
        self.allow_experimental = allow_experimental
        self._entries: dict[str, tuple[AnalyzerDefinition, AnalyzerFactory]] = {}

    def register(self, definition: AnalyzerDefinition, factory: AnalyzerFactory) -> None:
        if not callable(factory):
            log.error("invalid_factory", analyzer_id=definition.id)
            raise TypeError(f"factory for {definition.id!r} must be callable")
        if definition.id in self._entries:
            log.error("duplicate_analyzer_id", analyzer_id=definition.id)
            raise ValueError(f"analyzer id already registered: {definition.id}")
        # model_copy forces callers passing a subclass or mutable input through
        # the same Pydantic validation boundary before it becomes runnable.
        validated = AnalyzerDefinition.model_validate(definition.model_dump())
        self._entries[validated.id] = (validated, factory)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def definitions(self) -> tuple[AnalyzerDefinition, ...]:
        return tuple(self._entries[analyzer_id][0] for analyzer_id in self.ids())

    def plan(self, context: AnalyzerContext) -> tuple[PlannedAnalyzer, ...]:
        validated_context = AnalyzerContext.model_validate(context.model_dump())
        planned: list[PlannedAnalyzer] = []
        for analyzer_id in self.ids():
            definition, factory = self._entries[analyzer_id]
            missing = _missing_capabilities(definition, validated_context)
            disabled_reason = None
            if definition.experimental and not self.allow_experimental:
                disabled_reason = "experimental analyzer is disabled"
            if definition.enabled_by_mode and validated_context.mode not in definition.enabled_by_mode:
                disabled_reason = f"analyzer is disabled for mode {validated_context.mode}"
            planned.append(
                PlannedAnalyzer(
                    definition=definition,
                    factory=factory,
                    missing_capabilities=missing,
                    disabled_reason=disabled_reason,
                )
            )
        planned.sort(key=lambda item: (item.definition.phase, item.definition.cost, item.definition.id))
        log.debug(
            "planned",
            repo_id=validated_context.repo_id,
            head_sha=validated_context.head_sha,
            order=[item.definition.id for item in planned],
            skipped=[item.definition.id for item in planned if not item.ready],
        )
        return tuple(planned)

    def run(self, planned: PlannedAnalyzer, context: AnalyzerContext) -> AnalyzerResult:
        from .runner import run

        return run(planned, context)

    def run_all(self, context: AnalyzerContext) -> tuple[AnalyzerResult, ...]:
        return tuple(self.run(planned, context) for planned in self.plan(context))


registry = AnalyzerRegistry()

__all__ = ["AnalyzerFactory", "AnalyzerRegistry", "PlannedAnalyzer", "registry"]
