"""Failure-isolated execution of one planned analyzer."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, cast

import structlog
from pydantic import ValidationError

from .cache import FileAnalyzerCache
from .cache import cache_key as build_cache_key
from .contracts import AnalyzerContext, AnalyzerResult, AnalyzerStatus, Limitation
from .ports import CacheStore, ProcessExecutor
from .process import ProcessRequest, SubprocessProcess
from .registry import PlannedAnalyzer
from .validation import ResultValidationError, validate_result

log = structlog.get_logger(__name__)
cache_key = build_cache_key


def _run_key(planned: PlannedAnalyzer, context: AnalyzerContext) -> str:
    """Build a stable analyzer-scoped correlation key without logging context."""
    payload = {
        "repo_id": context.repo_id,
        "head_sha": context.head_sha,
        "as_of_ts": context.as_of_ts.isoformat(),
        "scope": context.scope,
        "mode": context.mode,
        "config_digest": context.config_digest,
        "analyzers": [planned.definition.id],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _failure_kind(result: AnalyzerResult) -> str | None:
    if result.status is not AnalyzerStatus.ERROR:
        return None
    error_type = result.diagnostics.get("error_type")
    if error_type:
        return str(error_type)
    if result.limitations:
        return result.limitations[0].kind
    return "error"


def _error_result(planned: PlannedAnalyzer, reason: str, *, kind: str) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_id=planned.definition.id,
        analyzer_version=planned.definition.version,
        status=AnalyzerStatus.ERROR,
        limitations=(Limitation(reason=reason, kind=kind),),  # type: ignore[arg-type]
    )


def _legacy_invalid_reason(error_type: str) -> str:
    return f"invalid analyzer result: {'ValueError' if error_type == 'identity' else 'ValidationError'}"


def _safe_exception_message(exc: BaseException) -> str:
    """Keep exception diagnostics useful without copying exception data to logs."""
    return f"{type(exc).__name__} (message redacted)"


def _native_event_fields(
    *,
    status: str,
    duration_ms: int,
    failure_kind: str | None,
    output: Any,
    run_key: str | None = None,
    repository_id: str | None = None,
    phase: str = "analyze",
    completed_phases: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Keep native helper logs correlated without recording command payloads."""
    return {
        "run_key": run_key,
        "repository_id": repository_id,
        "repo_id": repository_id,
        "phase": phase,
        "completed_phases": completed_phases,
        "status": status,
        "duration_ms": duration_ms,
        "failure_kind": failure_kind,
        "exit_code": output.exit_code,
        "timed_out": output.timed_out,
        "timeout": output.timed_out,
        "truncated": output.truncated,
        "cache_hit": False,
    }


def _cache_store(
    planned: PlannedAnalyzer, context: AnalyzerContext, cache: CacheStore | None
) -> CacheStore | None:
    if cache is not None:
        return cache
    if context.cache_dir is None:
        return None
    return cast(CacheStore, FileAnalyzerCache(context.cache_dir))


def _read_cache(
    planned: PlannedAnalyzer,
    context: AnalyzerContext,
    cache: CacheStore | None,
    *,
    correlation_key: str,
    completed_phases: tuple[str, ...] = (),
) -> AnalyzerResult | None:
    if not planned.definition.cache_policy.can_read:
        return None
    store = _cache_store(planned, context, cache)
    if store is None:
        return None
    key: str | None = None
    try:
        key = cache_key(planned, context)
        try:
            cached = store.get(
                key,
                analyzer_id=planned.definition.id,  # type: ignore[call-arg]
                analyzer_version=planned.definition.version,  # type: ignore[call-arg]
                run_key=correlation_key,
                repository_id=context.repo_id,
                phase="analyze",
                completed_phases=completed_phases,
            )
        except TypeError:
            cached = store.get(key)
        if cached is None:
            return None
        validated = validate_result(cached, planned.definition)
        if validated.analyzer_version != planned.definition.version:
            raise ResultValidationError(
                "cached analyzer version does not match", error_type="version"
            )
        if validated.status is AnalyzerStatus.ERROR:
            log.warning(
                "cache_error_result_miss",
                analyzer_id=planned.definition.id,
                analyzer_version=planned.definition.version,
                repository_id=context.repo_id,
                cache_key=key,
                cache_path=None,
                path=None,
                phase="analyze",
                completed_phases=completed_phases,
                status=validated.status.value,
                duration_ms=0,
                cache_hit=False,
                timeout=False,
                failure_kind="error_result",
                operation="read",
            )
            return None
        return validated.model_copy(update={"cache_hit": True})
    except ResultValidationError as exc:
        log.warning(
            "cache_read_failed",
            analyzer_id=planned.definition.id,
            analyzer_version=planned.definition.version,
            repository_id=context.repo_id,
            cache_key=key,
            cache_path=None,
            path=None,
            phase="analyze",
            completed_phases=completed_phases,
            status="cache_miss",
            duration_ms=0,
            cache_hit=False,
            timeout=False,
            failure_kind=exc.error_type,
            error_type=exc.error_type,
            operation="read",
        )
        return None
    except Exception as exc:
        log.warning(
            "cache_read_failed",
            analyzer_id=planned.definition.id,
            analyzer_version=planned.definition.version,
            repository_id=context.repo_id,
            cache_key=key,
            cache_path=None,
            path=None,
            phase="analyze",
            completed_phases=completed_phases,
            status="cache_miss",
            duration_ms=0,
            cache_hit=False,
            timeout=False,
            failure_kind=type(exc).__name__,
            error_type=type(exc).__name__,
            operation="read",
        )
        return None


def _write_cache(
    planned: PlannedAnalyzer,
    context: AnalyzerContext,
    result: AnalyzerResult,
    cache: CacheStore | None,
    *,
    correlation_key: str,
    completed_phases: tuple[str, ...] = (),
) -> None:
    if result.status is AnalyzerStatus.ERROR or not planned.definition.cache_policy.can_write:
        return
    store = _cache_store(planned, context, cache)
    if store is None:
        return
    key: str | None = None
    try:
        key = cache_key(planned, context)
        try:
            store.put(
                key,
                result,
                analyzer_id=planned.definition.id,  # type: ignore[call-arg]
                run_key=correlation_key,
                repository_id=context.repo_id,
                phase="analyze",
                completed_phases=completed_phases,
            )
        except TypeError:
            store.put(key, result)
    except Exception as exc:
        log.warning(
            "cache_write_failed",
            analyzer_id=planned.definition.id,
            analyzer_version=planned.definition.version,
            repository_id=context.repo_id,
            cache_key=key,
            cache_path=None,
            path=None,
            phase="analyze",
            completed_phases=completed_phases,
            status=result.status.value,
            duration_ms=0,
            cache_hit=False,
            timeout=False,
            failure_kind=type(exc).__name__,
            error_type=type(exc).__name__,
            operation="write",
        )


class AnalyzerRunner:
    """Run factories with a wait timeout; hard process termination is separate."""

    def __init__(
        self,
        *,
        cache: CacheStore | None = None,
        process_executor: ProcessExecutor | None = None,
    ) -> None:
        self.cache = cache
        self.process_executor = process_executor

    def run_json_command(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
        run_key: str | None = None,
        repository_id: str | None = None,
        phase: str = "analyze",
        completed_phases: tuple[str, ...] = (),
    ) -> Any:
        """Run a native JSON command through this runner's process port."""
        return run_json_command(
            command,
            cwd=cwd,
            timeout=timeout,
            process_executor=self.process_executor,
            run_key=run_key,
            repository_id=repository_id,
            phase=phase,
            completed_phases=completed_phases,
        )

    def run(
        self,
        planned: PlannedAnalyzer,
        context: AnalyzerContext,
        *,
        correlation_key: str | None = None,
        completed_phases: tuple[str, ...] = (),
    ) -> AnalyzerResult:
        definition = planned.definition
        correlation_key = correlation_key or _run_key(planned, context)
        common = {
            "analyzer_id": definition.id,
            "analyzer_version": definition.version,
            "run_key": correlation_key,
            "repository_id": context.repo_id,
            "repo_id": context.repo_id,
            "phase": "analyze",
            "completed_phases": completed_phases,
        }
        if planned.disabled_reason:
            log.warning(
                "analyzer_skipped",
                **common,
                status=AnalyzerStatus.SKIPPED.value,
                duration_ms=0,
                cache_hit=False,
                timeout=False,
                failure_kind="unsupported",
                reason=planned.disabled_reason,
            )
            result = AnalyzerResult.skipped(definition, planned.disabled_reason, kind="unsupported")
            log.info(
                "analyzer_finished",
                **common,
                status=result.status.value,
                duration_ms=0,
                cache_hit=False,
                timeout=False,
                failure_kind="unsupported",
            )
            return result
        if planned.missing_capabilities:
            reason = f"missing capabilities: {', '.join(planned.missing_capabilities)}"
            log.warning(
                "analyzer_skipped",
                **common,
                status=AnalyzerStatus.SKIPPED.value,
                duration_ms=0,
                cache_hit=False,
                timeout=False,
                failure_kind="missing_capability",
                reason=reason,
            )
            result = AnalyzerResult.skipped(definition, reason)
            log.info(
                "analyzer_finished",
                **common,
                status=result.status.value,
                duration_ms=0,
                cache_hit=False,
                timeout=False,
                failure_kind="missing_capability",
            )
            return result

        cached = _read_cache(
            planned,
            context,
            self.cache,
            correlation_key=correlation_key,
            completed_phases=completed_phases,
        )
        if cached is not None:
            cached = cached.model_copy(update={"cache_hit": True})
            log.info(
                "analyzer_finished",
                **common,
                status=cached.status.value,
                duration_ms=cached.duration_ms,
                cache_hit=True,
                timeout=False,
                failure_kind=_failure_kind(cached),
            )
            return cached

        started = time.perf_counter()
        log.info(
            "analyzer_started",
            **common,
            status="running",
            duration_ms=0,
            cache_hit=False,
            timeout=False,
            failure_kind=None,
        )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"analyzer-{definition.id}")
        future = executor.submit(planned.factory, context)
        timed_out = False
        failure_kind: str | None = None
        try:
            raw_result = future.result(timeout=definition.timeout)
            result = validate_result(raw_result, definition)
        except FutureTimeoutError:
            timed_out = True
            failure_kind = "timeout"
            future.cancel()
            result = _error_result(planned, "analyzer timed out", kind="timeout")
            log.warning(
                "analyzer_failed",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=True,
                failure_kind=failure_kind,
                error_type="timeout",
            )
        except ResultValidationError as exc:
            failure_kind = exc.error_type
            result = _error_result(planned, _legacy_invalid_reason(exc.error_type), kind="error")
            log.error(
                "invalid_result",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=False,
                failure_kind=failure_kind,
                error_type=exc.error_type,
            )
            log.debug(
                "analyzer_failure_detail",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=timed_out,
                failure_kind=failure_kind,
                error_type=exc.error_type,
                error_message=_safe_exception_message(exc),
            )
        except (ValidationError, TypeError, ValueError) as exc:
            failure_kind = type(exc).__name__
            result = _error_result(
                planned,
                f"invalid analyzer result: {type(exc).__name__}",
                kind="error",
            )
            log.error(
                "invalid_result",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=False,
                failure_kind=failure_kind,
                error_type=type(exc).__name__,
            )
            log.debug(
                "analyzer_failure_detail",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=False,
                failure_kind=failure_kind,
                error_type=type(exc).__name__,
                error_message=_safe_exception_message(exc),
            )
        except Exception as exc:
            failure_kind = type(exc).__name__
            result = _error_result(planned, "analyzer raised an exception", kind="error")
            log.error(
                "analyzer_failed",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=False,
                failure_kind=failure_kind,
                error_type=type(exc).__name__,
            )
            log.debug(
                "analyzer_failure_detail",
                **common,
                status=AnalyzerStatus.ERROR.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                cache_hit=False,
                timeout=False,
                failure_kind=failure_kind,
                error_type=type(exc).__name__,
                error_message=_safe_exception_message(exc),
            )
        finally:
            executor.shutdown(wait=not timed_out, cancel_futures=True)

        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        result = result.model_copy(update={"duration_ms": duration_ms, "cache_hit": False})
        if failure_kind is None:
            failure_kind = _failure_kind(result)
        _write_cache(
            planned,
            context,
            result,
            self.cache,
            correlation_key=correlation_key,
            completed_phases=completed_phases,
        )
        log.info(
            "analyzer_finished",
            **common,
            status=result.status.value,
            duration_ms=duration_ms,
            cache_hit=False,
            timeout=timed_out,
            failure_kind=failure_kind,
        )
        return result


def run(
    planned: PlannedAnalyzer,
    context: AnalyzerContext,
    *,
    cache: CacheStore | None = None,
    process_executor: ProcessExecutor | None = None,
    correlation_key: str | None = None,
    completed_phases: tuple[str, ...] = (),
) -> AnalyzerResult:
    return AnalyzerRunner(cache=cache, process_executor=process_executor).run(
        planned,
        context,
        correlation_key=correlation_key,
        completed_phases=completed_phases,
    )


def run_json_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    process_executor: ProcessExecutor | None = None,
    run_key: str | None = None,
    repository_id: str | None = None,
    phase: str = "analyze",
    completed_phases: tuple[str, ...] = (),
) -> Any:
    """Legacy-compatible JSON helper using the bounded native process boundary."""
    if not command:
        # Match subprocess.run([])'s legacy start-error category while keeping
        # all normal execution behind the injected process port.
        raise FileNotFoundError("native analyzer command is empty")
    executable, *args = command
    executor = process_executor if process_executor is not None else SubprocessProcess()
    output = executor.run(
        ProcessRequest(
            tool_id="native-json",
            executable=executable,
            args=tuple(args),
            cwd=cwd,
            timeout=timeout,
        )
    )
    if output.timed_out:
        log.warning(
            "native_json_timeout",
            **_native_event_fields(
                status="failed",
                duration_ms=output.duration_ms,
                failure_kind="timeout",
                output=output,
                run_key=run_key,
                repository_id=repository_id,
                phase=phase,
                completed_phases=completed_phases,
            ),
            tool_id=output.tool_id,
        )
        raise TimeoutError("native analyzer timed out")
    if output.exit_code is None:
        if output.start_error is not None:
            log.warning(
                "native_json_start_failed",
                **_native_event_fields(
                    status="failed",
                    duration_ms=output.duration_ms,
                    failure_kind=type(output.start_error).__name__,
                    output=output,
                    run_key=run_key,
                    repository_id=repository_id,
                    phase=phase,
                    completed_phases=completed_phases,
                ),
                tool_id=output.tool_id,
                error_type=type(output.start_error).__name__,
            )
            raise output.start_error
        error_type = (
            output.stderr
            if output.stderr
            in {
                "FileNotFoundError",
                "PermissionError",
                "NotADirectoryError",
            }
            else "OSError"
        )
        log.warning(
            "native_json_start_failed",
            **_native_event_fields(
                status="failed",
                duration_ms=output.duration_ms,
                failure_kind=error_type,
                output=output,
                run_key=run_key,
                repository_id=repository_id,
                phase=phase,
                completed_phases=completed_phases,
            ),
            tool_id=output.tool_id,
            error_type=error_type,
        )
        error_class = {
            "FileNotFoundError": FileNotFoundError,
            "PermissionError": PermissionError,
            "NotADirectoryError": NotADirectoryError,
        }.get(error_type, OSError)
        raise error_class from None
    if output.exit_code != 0:
        log.error(
            "native_json_failed",
            **_native_event_fields(
                status="failed",
                duration_ms=output.duration_ms,
                failure_kind="nonzero_exit",
                output=output,
                run_key=run_key,
                repository_id=repository_id,
                phase=phase,
                completed_phases=completed_phases,
            ),
            tool_id=output.tool_id,
        )
        raise RuntimeError(f"native analyzer exited with {output.exit_code}")
    try:
        import json

        result = json.loads(output.stdout)
        log.debug(
            "native_json_succeeded",
            **_native_event_fields(
                status="completed",
                duration_ms=output.duration_ms,
                failure_kind=None,
                output=output,
                run_key=run_key,
                repository_id=repository_id,
                phase=phase,
                completed_phases=completed_phases,
            ),
            tool_id=output.tool_id,
        )
        return result
    except ValueError as exc:
        log.error(
            "native_json_failed",
            **_native_event_fields(
                status="failed",
                duration_ms=output.duration_ms,
                failure_kind="invalid_json",
                output=output,
                run_key=run_key,
                repository_id=repository_id,
                phase=phase,
                completed_phases=completed_phases,
            ),
            tool_id=output.tool_id,
            error_type=type(exc).__name__,
        )
        raise ValueError("native analyzer returned non-JSON output") from exc


__all__ = ["AnalyzerRunner", "cache_key", "run", "run_json_command"]
