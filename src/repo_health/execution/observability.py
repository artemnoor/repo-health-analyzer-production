"""Best-effort execution telemetry port."""

from __future__ import annotations

from typing import Any, Protocol


class ExecutionTelemetry(Protocol):
    def record(self, event: str, fields: dict[str, Any]) -> None: ...


class NullTelemetry:
    def record(self, event: str, fields: dict[str, Any]) -> None:
        del event, fields


__all__ = ["ExecutionTelemetry", "NullTelemetry"]
