"""Shell-free, bounded subprocess execution for generic analyzers."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)
DEFAULT_OUTPUT_CAP = 16 * 1024 * 1024
ENV_ALLOWLIST = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)


def _trusted_taskkill_path() -> str:
    """Return the absolute Windows system utility used for tree cleanup."""
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or r"C:\Windows"
    candidate = os.path.join(system_root, "System32", "taskkill.exe")
    # A relative or malformed SystemRoot must never turn timeout cleanup into a
    # PATH lookup.  The fallback is intentionally absolute as well.
    if not os.path.isabs(candidate):
        candidate = r"C:\Windows\System32\taskkill.exe"
    return candidate


@dataclass(frozen=True)
class ProcessRequest:
    tool_id: str
    executable: str | Path
    args: tuple[str, ...] = ()
    cwd: Path = field(default_factory=Path.cwd)
    environment: Mapping[str, str] | None = None
    stdin: str | bytes | None = None
    timeout: float = 120.0
    output_cap: int = DEFAULT_OUTPUT_CAP
    run_key: str | None = None
    repository_id: str | None = None
    phase: str = "analyze"
    completed_phases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.output_cap <= 0:
            raise ValueError("output_cap must be positive")


@dataclass(frozen=True)
class ProcessOutput:
    tool_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False
    start_error: OSError | None = None


def _bounded_reader(stream, cap: int, result: list[bytes], truncated: list[bool]) -> None:
    captured = bytearray()
    while True:
        try:
            chunk = stream.read(1024 * 1024)
        except (OSError, ValueError):
            break
        if not chunk:
            break
        remaining = cap - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > max(remaining, 0):
            truncated[0] = True
    result.append(bytes(captured))


def _safe_environment(request: ProcessRequest) -> dict[str, str]:
    source = request.environment if request.environment is not None else os.environ
    return {key: value for key, value in source.items() if key.upper() in ENV_ALLOWLIST}


def _terminate_process_tree(process: subprocess.Popen[bytes], *, request: ProcessRequest | None = None) -> None:
    """Terminate the timed-out process and children that inherited its pipes."""
    tool_id = request.tool_id if request is not None else None
    if os.name == "nt":
        try:
            result = subprocess.run(
                [_trusted_taskkill_path(), "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                return
            log.warning(
                "process_tree_kill_failed",
                **(
                    _event_fields(
                        request,
                        exit_code=None,
                        duration_ms=0,
                        timed_out=True,
                        truncated=False,
                        failure_kind="taskkill_nonzero",
                    )
                    if request is not None
                    else {
                        "run_key": None,
                        "repository_id": None,
                        "phase": "analyze",
                        "completed_phases": (),
                        "status": "failed",
                        "exit_code": None,
                        "duration_ms": 0,
                        "timed_out": True,
                        "truncated": False,
                        "failure_kind": "taskkill_nonzero",
                    }
                ),
                tool_id=tool_id,
                return_code=result.returncode,
            )
        except (OSError, subprocess.TimeoutExpired):
            log.warning(
                "process_tree_kill_failed",
                **(
                    _event_fields(
                        request,
                        exit_code=None,
                        duration_ms=0,
                        timed_out=True,
                        truncated=False,
                        failure_kind="taskkill_error",
                    )
                    if request is not None
                    else {
                        "run_key": None,
                        "repository_id": None,
                        "phase": "analyze",
                        "completed_phases": (),
                        "status": "failed",
                        "exit_code": None,
                        "duration_ms": 0,
                        "timed_out": True,
                        "truncated": False,
                        "failure_kind": "taskkill_error",
                    }
                ),
                tool_id=tool_id,
            )
    else:
        killpg = getattr(os, "killpg", None)
        try:
            if callable(killpg):
                killpg(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
                return
        except (OSError, ProcessLookupError):
            pass
    with suppress(OSError):
        process.kill()


def _event_fields(
    request: ProcessRequest,
    *,
    exit_code: int | None,
    duration_ms: int,
    timed_out: bool,
    truncated: bool,
    failure_kind: str | None,
) -> dict[str, Any]:
    """Return the redacted correlation fields shared by process events."""
    return {
        "run_key": request.run_key,
        "repository_id": request.repository_id,
        "repo_id": request.repository_id,
        "phase": request.phase,
        "completed_phases": request.completed_phases,
        "status": "timeout" if timed_out else "failed" if failure_kind else "completed",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "timed_out": timed_out,
        "timeout": timed_out,
        "truncated": truncated,
        "cache_hit": False,
        "failure_kind": failure_kind,
    }


class SubprocessProcess:
    """Execute one explicit argv request and kill it on a hard timeout."""

    def run(self, request: ProcessRequest) -> ProcessOutput:
        command = [str(request.executable), *(str(arg) for arg in request.args)]
        started = time.perf_counter()
        log.debug(
            "process_started",
            **_event_fields(
                request,
                exit_code=None,
                duration_ms=0,
                timed_out=False,
                truncated=False,
                failure_kind=None,
            ),
            tool_id=request.tool_id,
            arg_count=len(request.args),
            timeout_seconds=request.timeout,
            output_cap=request.output_cap,
            stdin_present=request.stdin is not None,
        )
        try:
            popen_kwargs: dict[str, Any] = {
                "cwd": str(Path(request.cwd).resolve()),
                "env": _safe_environment(request),
                "stdin": subprocess.PIPE if request.stdin is not None else None,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "shell": False,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(
                command,
                **popen_kwargs,
            )
        except OSError as exc:
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            log.error(
                "process_start_failed",
                **_event_fields(
                    request,
                    exit_code=None,
                    duration_ms=duration_ms,
                    timed_out=False,
                    truncated=False,
                    failure_kind=type(exc).__name__,
                ),
                tool_id=request.tool_id,
                operation="start",
                error_type=type(exc).__name__,
                arg_count=len(request.args),
                timeout_seconds=request.timeout,
                output_cap=request.output_cap,
                stdin_present=request.stdin is not None,
            )
            return ProcessOutput(
                request.tool_id,
                None,
                "",
                type(exc).__name__,
                duration_ms,
                start_error=exc,
            )

        stdout_bytes: list[bytes] = []
        stderr_bytes: list[bytes] = []
        stdout_truncated = [False]
        stderr_truncated = [False]
        assert process.stdout is not None and process.stderr is not None
        readers = (
            threading.Thread(
                target=_bounded_reader,
                args=(process.stdout, request.output_cap, stdout_bytes, stdout_truncated),
                daemon=True,
            ),
            threading.Thread(
                target=_bounded_reader,
                args=(process.stderr, request.output_cap, stderr_bytes, stderr_truncated),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        timed_out = False
        stdin_writer: threading.Thread | None = None
        if request.stdin is not None and process.stdin is not None:
            input_bytes = request.stdin.encode("utf-8") if isinstance(request.stdin, str) else request.stdin

            def write_stdin() -> None:
                assert process.stdin is not None
                try:
                    process.stdin.write(input_bytes)
                    process.stdin.close()
                except (OSError, ValueError) as exc:
                    log.debug(
                        "process_stdin_write_failed",
                        **_event_fields(
                            request,
                            exit_code=None,
                            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                            timed_out=timed_out,
                            truncated=stdout_truncated[0] or stderr_truncated[0],
                            failure_kind=type(exc).__name__,
                        ),
                        tool_id=request.tool_id,
                        operation="stdin_write",
                        error_type=type(exc).__name__,
                    )

            stdin_writer = threading.Thread(
                target=write_stdin,
                name=f"process-stdin-{request.tool_id}",
                daemon=True,
            )
            stdin_writer.start()

        try:
            remaining = max(0.0, request.timeout - (time.perf_counter() - started))
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            log.warning(
                "process_timeout",
                **_event_fields(
                    request,
                    exit_code=None,
                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                    timed_out=True,
                    truncated=stdout_truncated[0] or stderr_truncated[0],
                    failure_kind="timeout",
                ),
                tool_id=request.tool_id,
            )
            _terminate_process_tree(process, request=request)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    with suppress(OSError, ValueError):
                        stream.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.error(
                    "process_termination_timeout",
                    **_event_fields(
                        request,
                        exit_code=process.poll(),
                        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                        timed_out=True,
                        truncated=stdout_truncated[0] or stderr_truncated[0],
                        failure_kind="termination_timeout",
                    ),
                    tool_id=request.tool_id,
                )
                with suppress(OSError):
                    process.kill()
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)

        if stdin_writer is not None:
            stdin_writer.join(timeout=1.0)
            if stdin_writer.is_alive():
                log.debug(
                    "process_stdin_write_timeout",
                    **_event_fields(
                        request,
                        exit_code=process.poll(),
                        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                        timed_out=timed_out,
                        truncated=stdout_truncated[0] or stderr_truncated[0],
                        failure_kind="stdin_write_timeout",
                    ),
                    tool_id=request.tool_id,
                    operation="stdin_write",
                )
        for reader in readers:
            reader.join(timeout=1.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()
        output = ProcessOutput(
            tool_id=request.tool_id,
            exit_code=process.returncode,
            stdout=(stdout_bytes[0] if stdout_bytes else b"").decode("utf-8", errors="replace"),
            stderr=(stderr_bytes[0] if stderr_bytes else b"").decode("utf-8", errors="replace"),
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            timed_out=timed_out,
            truncated=stdout_truncated[0] or stderr_truncated[0],
        )
        log.info(
            "process_finished",
            **_event_fields(
                request,
                exit_code=output.exit_code,
                duration_ms=output.duration_ms,
                timed_out=output.timed_out,
                truncated=output.truncated,
                failure_kind=(
                    "timeout" if output.timed_out else "nonzero_exit" if output.exit_code not in (None, 0) else None
                ),
            ),
            tool_id=output.tool_id,
        )
        return output


Process = SubprocessProcess

__all__ = [
    "DEFAULT_OUTPUT_CAP",
    "ENV_ALLOWLIST",
    "Process",
    "ProcessOutput",
    "ProcessRequest",
    "SubprocessProcess",
]
