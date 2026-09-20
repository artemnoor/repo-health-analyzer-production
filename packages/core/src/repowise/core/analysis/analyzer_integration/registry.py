"""Explicit analyzer registration and deterministic capability planning."""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from .contracts import AnalyzerContext, AnalyzerDefinition, AnalyzerResult
from .ports import AnalyzerFactory

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PlannedAnalyzer:
    definition: AnalyzerDefinition
    factory: AnalyzerFactory
    missing_capabilities: tuple[str, ...] = ()
    disabled_reason: str | None = None

    @property
    def ready(self) -> bool:
        return not self.missing_capabilities and self.disabled_reason is None


def _missing_capabilities(
    definition: AnalyzerDefinition, context: AnalyzerContext
) -> tuple[str, ...]:
    available = set(context.capabilities)
    missing = [requirement for requirement in definition.requires if requirement not in available]
    supported = context.inventory.get("languages")
    if definition.supports and supported:
        languages = {str(language) for language in supported}
        if not languages.intersection(definition.supports):
            missing.append(f"unsupported:{','.join(definition.supports)}")
    return tuple(sorted(set(missing)))


class AnalyzerRegistry:
    """Own analyzer identity; registration never discovers adapters implicitly."""

    def __init__(
        self,
        *,
        allow_experimental: bool = False,
        emit_registration_logs: bool = True,
    ) -> None:
        self.allow_experimental = allow_experimental
        self.emit_registration_logs = emit_registration_logs
        self._entries: dict[str, tuple[AnalyzerDefinition, AnalyzerFactory]] = {}

    def register(self, definition: AnalyzerDefinition, factory: AnalyzerFactory) -> None:
        if not callable(factory):
            log.error(
                "invalid_factory",
                run_key=None,
                repository_id=None,
                repo_id=None,
                phase="register",
                completed_phases=(),
                status="failed",
                duration_ms=0,
                failure_kind="invalid_factory",
                analyzer_id=getattr(definition, "id", "<invalid>"),
            )
            raise TypeError(
                f"factory for {getattr(definition, 'id', '<invalid>')!r} must be callable"
            )
        validated = AnalyzerDefinition.model_validate(
            definition.model_dump() if isinstance(definition, AnalyzerDefinition) else definition
        )
        if validated.id in self._entries:
            log.error(
                "duplicate_analyzer_id",
                run_key=None,
                repository_id=None,
                repo_id=None,
                phase="register",
                completed_phases=(),
                status="failed",
                duration_ms=0,
                failure_kind="duplicate_id",
                analyzer_id=validated.id,
            )
            raise ValueError(f"analyzer id already registered: {validated.id}")
        self._entries[validated.id] = (validated, factory)
        if self.emit_registration_logs:
            log.debug(
                "analyzer_registered",
                run_key=None,
                repository_id=None,
                repo_id=None,
                phase="register",
                completed_phases=(),
                status="completed",
                duration_ms=0,
                failure_kind=None,
                analyzer_id=validated.id,
                analyzer_version=validated.version,
            )

    def unregister(self, analyzer_id: str) -> None:
        removed = analyzer_id in self._entries
        self._entries.pop(analyzer_id, None)
        log.debug(
            "analyzer_unregistered",
            run_key=None,
            repository_id=None,
            repo_id=None,
            phase="register",
            completed_phases=(),
            status="completed",
            duration_ms=0,
            failure_kind=None,
            analyzer_id=analyzer_id,
            removed=removed,
        )

    def clear(self) -> None:
        removed_ids = self.ids()
        self._entries.clear()
        log.debug(
            "registry_cleared",
            run_key=None,
            repository_id=None,
            repo_id=None,
            phase="register",
            completed_phases=(),
            status="completed",
            duration_ms=0,
            failure_kind=None,
            analyzer_ids=removed_ids,
            analyzer_count=len(removed_ids),
        )

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def definitions(self) -> tuple[AnalyzerDefinition, ...]:
        return tuple(self._entries[analyzer_id][0] for analyzer_id in self.ids())

    def get(self, analyzer_id: str) -> tuple[AnalyzerDefinition, AnalyzerFactory] | None:
        return self._entries.get(analyzer_id)

    def plan(
        self,
        context: AnalyzerContext,
        *,
        run_key_value: str | None = None,
    ) -> tuple[PlannedAnalyzer, ...]:
        started = time.perf_counter()
        validated_context = AnalyzerContext.model_validate(context.model_dump())
        planned: list[PlannedAnalyzer] = []
        for analyzer_id in self.ids():
            definition, factory = self._entries[analyzer_id]
            disabled_reason = None
            if definition.experimental and not self.allow_experimental:
                disabled_reason = "experimental analyzer is disabled"
            if (
                definition.enabled_by_mode
                and validated_context.mode not in definition.enabled_by_mode
            ):
                disabled_reason = f"analyzer is disabled for mode {validated_context.mode}"
            planned.append(
                PlannedAnalyzer(
                    definition=definition,
                    factory=factory,
                    missing_capabilities=_missing_capabilities(definition, validated_context),
                    disabled_reason=disabled_reason,
                )
            )
        planned.sort(
            key=lambda item: (item.definition.phase, item.definition.cost, item.definition.id)
        )
        log.info(
            "analyzers_planned",
            run_key=run_key_value,
            phase="plan",
            status="completed",
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            failure_kind=None,
            repository_id=validated_context.repo_id,
            repo_id=validated_context.repo_id,
            completed_phases=(),
            analyzer_count=len(planned),
            skipped_analyzer_ids=tuple(item.definition.id for item in planned if not item.ready),
            analyzer_ids=tuple(item.definition.id for item in planned),
            analyzer_metadata=tuple(
                {
                    "id": item.definition.id,
                    "version": item.definition.version,
                    "phase": item.definition.phase,
                    "cost": item.definition.cost,
                    "timeout": item.definition.timeout,
                    "cache_policy": item.definition.cache_policy.value,
                    "source_commit": item.definition.source_commit,
                    "experimental": item.definition.experimental,
                    "enabled_by_mode": item.definition.enabled_by_mode,
                    "requires": item.definition.requires,
                    "supports": item.definition.supports,
                }
                for item in planned
            ),
        )
        return tuple(planned)

    def run(self, planned: PlannedAnalyzer, context: AnalyzerContext) -> AnalyzerResult:
        from .runner import run

        return run(planned, context)

    def run_all(self, context: AnalyzerContext) -> tuple[AnalyzerResult, ...]:
        return tuple(self.run(planned, context) for planned in self.plan(context))


registry = AnalyzerRegistry()

__all__ = ["AnalyzerFactory", "AnalyzerRegistry", "PlannedAnalyzer", "registry"]
