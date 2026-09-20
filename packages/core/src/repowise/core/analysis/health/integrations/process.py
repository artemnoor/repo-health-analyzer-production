"""Compatibility facade preserving the legacy NativeProcess API."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from repowise.core.analysis.analyzer_integration.process import (
    DEFAULT_OUTPUT_CAP,
    ENV_ALLOWLIST,
    ProcessOutput,
    ProcessRequest,
    SubprocessProcess,
)

from .contracts import AnalyzerContext


def workspace_root() -> Path:
    """Find the checkout root for legacy adapters only."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "vendor" / "SOURCES.lock").is_file():
            return parent
    return Path.cwd()


class NativeProcess:
    """Translate the old context-aware call shape to the neutral process port."""

    def __init__(self, *, output_cap: int = DEFAULT_OUTPUT_CAP) -> None:
        if output_cap <= 0:
            raise ValueError("output_cap must be positive")
        self.output_cap = output_cap
        self._process = SubprocessProcess()

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
        return self._process.run(
            ProcessRequest(
                tool_id=tool_id,
                executable=executable,
                args=tuple(str(arg) for arg in args),
                cwd=Path(cwd or context.repo_path).resolve(),
                environment={
                    key: value for key, value in os.environ.items() if key.upper() in ENV_ALLOWLIST
                },
                stdin=stdin,
                timeout=timeout,
                output_cap=self.output_cap,
            )
        )


__all__ = [
    "DEFAULT_OUTPUT_CAP",
    "ENV_ALLOWLIST",
    "NativeProcess",
    "ProcessOutput",
    "ProcessRequest",
    "workspace_root",
]
