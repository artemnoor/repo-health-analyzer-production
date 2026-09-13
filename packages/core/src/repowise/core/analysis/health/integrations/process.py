"""Secure, bounded subprocess boundary for copied native analyzers."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import structlog

from .contracts import AnalyzerContext

log = structlog.get_logger("native.process")
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


@dataclass(frozen=True)
class ProcessOutput:
    tool_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False


def workspace_root() -> Path:
    """Find the checkout root without relying on the caller's current cwd."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "vendor" / "SOURCES.lock").is_file():
            return parent
    return Path.cwd()


def _bounded_reader(stream, cap: int, result: list[bytes], truncated: list[bool]) -> None:
    captured = bytearray()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        remaining = cap - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > max(remaining, 0):
            truncated[0] = True
    result.append(bytes(captured))


class NativeProcess:
    """Run one argv list with output, environment and time bounds."""

    def __init__(self, *, output_cap: int = DEFAULT_OUTPUT_CAP) -> None:
        if output_cap <= 0:
            raise ValueError("output_cap must be positive")
        self.output_cap = output_cap

    def run(
        self,
        tool_id: str,
        executable: str | Path,
        args: Sequence[str],
        context: AnalyzerContext,
        *,
        timeout: float = 120.0,
        cwd: Path | None = None,
        stdin: str | bytes | None = None,
    ) -> ProcessOutput:
        command = [str(executable), *(str(arg) for arg in args)]
        process_cwd = Path(cwd or context.repo_path).resolve()
        environment = {key: value for key, value in os.environ.items() if key.upper() in ENV_ALLOWLIST}
        log.debug(
            "process_started",
            tool_id=tool_id,
            executable=str(executable),
            arg_count=len(args),
            repo_id=context.repo_id,
            head_sha=context.head_sha,
            timeout=timeout,
        )
        started = time.perf_counter()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(process_cwd),
                env=environment,
                stdin=subprocess.PIPE if stdin is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            log.error("process_start_failed", tool_id=tool_id, error_type=type(exc).__name__)
            return ProcessOutput(tool_id, None, "", type(exc).__name__, duration_ms)

        stdout_bytes: list[bytes] = []
        stderr_bytes: list[bytes] = []
        stdout_truncated = [False]
        stderr_truncated = [False]
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_thread = threading.Thread(
            target=_bounded_reader,
            args=(process.stdout, self.output_cap, stdout_bytes, stdout_truncated),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_bounded_reader,
            args=(process.stderr, self.output_cap, stderr_bytes, stderr_truncated),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        if stdin is not None and process.stdin is not None:
            input_bytes = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
            try:
                process.stdin.write(input_bytes)
                process.stdin.close()
            except OSError:
                pass
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait()
        stdout_thread.join()
        stderr_thread.join()
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        truncated = stdout_truncated[0] or stderr_truncated[0]
        output = ProcessOutput(
            tool_id=tool_id,
            exit_code=process.returncode,
            stdout=(stdout_bytes[0] if stdout_bytes else b"").decode("utf-8", errors="replace"),
            stderr=(stderr_bytes[0] if stderr_bytes else b"").decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=truncated,
        )
        log.info(
            "process_finished tool_id=%s exit_code=%s duration_ms=%d stdout_bytes=%d stderr_bytes=%d truncated=%s",
            tool_id,
            output.exit_code,
            output.duration_ms,
            len(output.stdout.encode("utf-8")),
            len(output.stderr.encode("utf-8")),
            output.truncated,
        )
        return output


__all__ = ["DEFAULT_OUTPUT_CAP", "NativeProcess", "ProcessOutput", "workspace_root"]
