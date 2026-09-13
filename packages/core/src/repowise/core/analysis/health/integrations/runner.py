"""Failure-isolated execution for planned analyzers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contracts import AnalyzerContext, AnalyzerResult, AnalyzerStatus, Limitation
from .registry import PlannedAnalyzer

log = logging.getLogger("health.runner")


def cache_key(planned: PlannedAnalyzer, context: AnalyzerContext) -> str:
    payload = {
        "analyzer_id": planned.definition.id,
        "version": planned.definition.version,
        "source_commit": planned.definition.source_commit,
        "repo_id": context.repo_id,
        "head_sha": context.head_sha,
        "as_of_ts": context.as_of_ts.isoformat(),
        "scope": context.scope,
        "mode": context.mode,
        "config_digest": context.config_digest,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _cache_path(planned: PlannedAnalyzer, context: AnalyzerContext) -> Path | None:
    if context.cache_dir is None:
        return None
    return context.cache_dir / "health-analyzers" / f"{planned.definition.id}-{cache_key(planned, context)}.json"


def _read_cache(planned: PlannedAnalyzer, context: AnalyzerContext) -> AnalyzerResult | None:
    path = _cache_path(planned, context)
    if path is None or not planned.definition.cache_policy.can_read or not path.is_file():
        return None
    try:
        result = AnalyzerResult.model_validate_json(path.read_text(encoding="utf-8"))
        return result.model_copy(update={"cache_hit": True})
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("cache_read_failed analyzer_id=%s reason=%s", planned.definition.id, type(exc).__name__)
        return None


def _write_cache(planned: PlannedAnalyzer, context: AnalyzerContext, result: AnalyzerResult) -> None:
    path = _cache_path(planned, context)
    if path is None or not planned.definition.cache_policy.can_write:
        return
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(result.model_dump_json(), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        log.warning("cache_write_failed analyzer_id=%s reason=%s", planned.definition.id, type(exc).__name__)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _error_result(planned: PlannedAnalyzer, status: AnalyzerStatus, reason: str, *, kind: str) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=planned.definition.id,
        analyzer_version=planned.definition.version,
        status=status,
        limitations=(Limitation(reason=reason, kind=kind),),  # type: ignore[arg-type]
    )


def run(planned: PlannedAnalyzer, context: AnalyzerContext) -> AnalyzerResult:
    """Run one planned analyzer and convert failures into an isolated result."""
    definition = planned.definition
    if planned.disabled_reason:
        log.warning("analyzer_skipped analyzer_id=%s reason=%s", definition.id, planned.disabled_reason)
        return AnalyzerResult.skipped(definition, planned.disabled_reason, kind="unsupported")
    if planned.missing_capabilities:
        reason = f"missing capabilities: {', '.join(planned.missing_capabilities)}"
        log.warning("analyzer_skipped analyzer_id=%s reason=%s", definition.id, reason)
        return AnalyzerResult.skipped(definition, reason)

    cached = _read_cache(planned, context)
    if cached is not None:
        log.info("analyzer_finished analyzer_id=%s status=%s cache_hit=true", definition.id, cached.status.value)
        return cached

    started = time.perf_counter()
    log.info("analyzer_started analyzer_id=%s repo_id=%s head_sha=%s", definition.id, context.repo_id, context.head_sha)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"health-{definition.id}")
    future = executor.submit(planned.factory, context)
    timed_out = False
    try:
        raw_result = future.result(timeout=definition.timeout)
        result = AnalyzerResult.model_validate(raw_result)
        if result.analyzer_id != definition.id:
            raise ValueError(f"result analyzer_id {result.analyzer_id!r} does not match {definition.id!r}")
    except FutureTimeoutError:
        timed_out = True
        future.cancel()
        result = _error_result(planned, AnalyzerStatus.ERROR, "analyzer timed out", kind="timeout")
    except (ValidationError, TypeError, ValueError) as exc:
        result = _error_result(planned, AnalyzerStatus.ERROR, f"invalid analyzer result: {type(exc).__name__}", kind="error")
        log.error("invalid_result analyzer_id=%s error_type=%s", definition.id, type(exc).__name__)
    except Exception as exc:
        result = _error_result(planned, AnalyzerStatus.ERROR, "analyzer raised an exception", kind="error")
        log.error("analyzer_failed analyzer_id=%s error_type=%s", definition.id, type(exc).__name__)
    finally:
        executor.shutdown(wait=not timed_out, cancel_futures=True)

    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    result = result.model_copy(update={"duration_ms": duration_ms, "cache_hit": False})
    if result.status != AnalyzerStatus.ERROR:
        _write_cache(planned, context, result)
    log.info(
        "analyzer_finished analyzer_id=%s status=%s duration_ms=%d cache_hit=false evidence=%d",
        definition.id,
        result.status.value,
        duration_ms,
        len(result.evidence),
    )
    return result


def run_json_command(command: Sequence[str], *, cwd: Path, timeout: float) -> Any:
    """Execute a native tool at a subprocess boundary and require JSON output."""
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("native analyzer timed out") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"native analyzer exited with {completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("native analyzer returned non-JSON output") from exc


__all__ = ["cache_key", "run", "run_json_command"]
