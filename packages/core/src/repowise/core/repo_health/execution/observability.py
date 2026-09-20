"""Small observability port with deterministic redaction for task execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

_SECRET_KEYS = frozenset({"api_key", "apikey", "authorization", "password", "secret", "token"})


class ExecutionTelemetry(Protocol):
    def record(self, event: str, fields: Mapping[str, Any]) -> None: ...


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Drop secret-bearing values before logs, metrics, or traces receive them."""

    redacted: dict[str, Any] = {}
    for key, value in fields.items():
        normalized = str(key).casefold().replace("-", "_")
        if any(marker in normalized for marker in _SECRET_KEYS):
            redacted[str(key)] = "[REDACTED]"
        elif isinstance(value, Mapping):
            redacted[str(key)] = redact_fields(value)
        else:
            redacted[str(key)] = value
    return redacted


class InMemoryTelemetry:
    """Test/local sink; production can replace it with metrics/tracing exporters."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event: str, fields: Mapping[str, Any]) -> None:
        self.events.append((event, redact_fields(fields)))


__all__ = ["ExecutionTelemetry", "InMemoryTelemetry", "redact_fields"]
