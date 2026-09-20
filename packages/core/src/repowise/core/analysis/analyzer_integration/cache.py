"""Failure-tolerant cache primitives for analyzer results."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import structlog
from pydantic import ValidationError

from .contracts import AnalyzerContext, AnalyzerDefinition, AnalyzerResult, CachePolicy

log = structlog.get_logger(__name__)
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_component(value: str, name: str) -> str:
    """Validate a cache path component before it reaches ``Path``."""
    if not isinstance(value, str) or not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"invalid cache {name}")
    return value


def cache_key(definition: AnalyzerDefinition | Any, context: AnalyzerContext) -> str:
    """Return the stable baseline key for an analyzer/context pair."""
    definition_value = cast(Any, definition)
    payload = {
        "analyzer_id": definition_value.id
        if hasattr(definition_value, "id")
        else definition_value.definition.id,
        "version": definition_value.version
        if hasattr(definition_value, "version")
        else definition_value.definition.version,
        "source_commit": (
            definition_value.source_commit
            if hasattr(definition_value, "source_commit")
            else definition_value.definition.source_commit
        ),
        "repo_id": context.repo_id,
        "head_sha": context.head_sha,
        "as_of_ts": context.as_of_ts.isoformat(),
        "scope": context.scope,
        "mode": context.mode,
        "config_digest": context.config_digest,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cache_filename(definition: AnalyzerDefinition | Any, context: AnalyzerContext) -> str:
    definition_value = cast(Any, definition)
    analyzer_id = (
        definition_value.id if hasattr(definition_value, "id") else definition_value.definition.id
    )
    _validate_component(analyzer_id, "analyzer id")
    return f"{analyzer_id}-{cache_key(definition, context)}.json"


class FileAnalyzerCache:
    """JSON cache with atomic writes and corrupt-entry-as-miss semantics."""

    def __init__(self, root: Path, *, namespace: str = "health-analyzers") -> None:
        self.root = Path(root).resolve()
        self.namespace = _validate_component(namespace, "namespace")

    def path_for(self, key: str, *, analyzer_id: str | None = None) -> Path:
        _validate_component(key, "key")
        if analyzer_id is not None:
            _validate_component(analyzer_id, "analyzer id")
        filename = f"{analyzer_id}-{key}.json" if analyzer_id else f"{key}.json"
        path = (self.root / self.namespace / filename).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("cache path escapes cache root") from exc
        return path

    def get(
        self,
        key: str,
        *,
        analyzer_id: str | None = None,
        analyzer_version: str | None = None,
        run_key: str | None = None,
        repository_id: str | None = None,
        phase: str = "analyze",
        completed_phases: tuple[str, ...] = (),
    ) -> AnalyzerResult | None:
        path = self.path_for(key, analyzer_id=analyzer_id)
        started = time.perf_counter()
        metadata = {
            "cache_key": key,
            "cache_path": str(path),
            "path": str(path),
            "analyzer_id": analyzer_id,
            "analyzer_version": analyzer_version,
            "run_key": run_key,
            "repository_id": repository_id,
            "repo_id": repository_id,
            "phase": phase,
            "completed_phases": completed_phases,
            "status": "running",
            "cache_hit": False,
            "timeout": False,
            "failure_kind": None,
        }
        if not path.is_file():
            metadata["status"] = "cache_miss"
            metadata["failure_kind"] = "missing"
            log.debug(
                "cache_miss",
                **metadata,
                operation="read",
                result_status=None,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return None
        try:
            result = AnalyzerResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError) as exc:
            metadata["status"] = "cache_miss"
            metadata["failure_kind"] = type(exc).__name__
            log.warning(
                "cache_read_failed",
                **metadata,
                operation="read",
                result_status=None,
                reason=type(exc).__name__,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return None
        if analyzer_id is not None and result.analyzer_id != analyzer_id:
            metadata["status"] = "cache_miss"
            metadata["failure_kind"] = "identity_mismatch"
            log.warning(
                "cache_identity_mismatch",
                **metadata,
                result_status=result.status.value,
                operation="read",
                expected_analyzer_id=analyzer_id,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return None
        if analyzer_version is not None and result.analyzer_version != analyzer_version:
            metadata["status"] = "cache_miss"
            metadata["failure_kind"] = "version_mismatch"
            log.warning(
                "cache_version_mismatch",
                **metadata,
                result_status=result.status.value,
                operation="read",
                expected_analyzer_version=analyzer_version,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return None
        if result.status.value == "error":
            metadata["status"] = "cache_miss"
            metadata["failure_kind"] = "error_result"
            log.warning(
                "cache_error_result_miss",
                **metadata,
                result_status=result.status.value,
                operation="read",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return None
        metadata["status"] = "completed"
        metadata["cache_hit"] = True
        log.debug(
            "cache_hit",
            **metadata,
            result_status=result.status.value,
            operation="read",
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        )
        return result.model_copy(update={"cache_hit": True})

    def put(
        self,
        key: str,
        result: AnalyzerResult,
        *,
        analyzer_id: str | None = None,
        run_key: str | None = None,
        repository_id: str | None = None,
        phase: str = "analyze",
        completed_phases: tuple[str, ...] = (),
    ) -> None:
        path = self.path_for(key, analyzer_id=analyzer_id)
        started = time.perf_counter()
        metadata = {
            "cache_key": key,
            "cache_path": str(path),
            "path": str(path),
            "analyzer_id": analyzer_id or result.analyzer_id,
            "analyzer_version": result.analyzer_version,
            "result_status": result.status.value,
            "run_key": run_key,
            "repository_id": repository_id,
            "repo_id": repository_id,
            "phase": phase,
            "completed_phases": completed_phases,
            "status": result.status.value,
            "cache_hit": False,
            "timeout": False,
            "failure_kind": None,
        }
        if result.status.value == "error":
            metadata["status"] = "skipped"
            metadata["failure_kind"] = "error_result"
            log.debug(
                "cache_write_skipped",
                **metadata,
                operation="write",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(result.model_copy(update={"cache_hit": False}).model_dump_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            metadata["status"] = "completed"
            log.debug(
                "cache_write",
                **metadata,
                operation="write",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
        except OSError as exc:
            metadata["status"] = "failed"
            metadata["failure_kind"] = type(exc).__name__
            log.warning(
                "cache_write_failed",
                **metadata,
                operation="write",
                reason=type(exc).__name__,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()

    def load_for(
        self,
        definition: AnalyzerDefinition | Any,
        context: AnalyzerContext,
    ) -> AnalyzerResult | None:
        definition_value = cast(Any, definition)
        return self.get(
            cache_key(definition, context),
            analyzer_id=definition_value.id
            if hasattr(definition_value, "id")
            else definition_value.definition.id,
            analyzer_version=definition_value.version
            if hasattr(definition_value, "version")
            else definition_value.definition.version,
        )

    def save_for(
        self,
        definition: AnalyzerDefinition | Any,
        context: AnalyzerContext,
        result: AnalyzerResult,
    ) -> None:
        definition_value = cast(Any, definition)
        self.put(
            cache_key(definition, context),
            result,
            analyzer_id=definition_value.id
            if hasattr(definition_value, "id")
            else definition_value.definition.id,
        )


def policy_allows_read(policy: CachePolicy) -> bool:
    return policy.can_read


def policy_allows_write(policy: CachePolicy) -> bool:
    return policy.can_write


AnalyzerCache = FileAnalyzerCache


__all__ = [
    "AnalyzerCache",
    "FileAnalyzerCache",
    "cache_filename",
    "cache_key",
    "policy_allows_read",
    "policy_allows_write",
]
