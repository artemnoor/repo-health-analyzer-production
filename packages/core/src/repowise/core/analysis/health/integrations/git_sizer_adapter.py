"""Bounded adapter for the official git-sizer JSON v2 CLI boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Protocol

import structlog

from ....analysis.analyzer_integration.ports import ProcessExecutor
from .code_health_facts import (
    CodeHealthEvidenceFact,
    CodeHealthPolicy,
    CodeHealthStatus,
    GitStructureFacts,
    stable_digest,
)
from .contracts import AnalyzerContext
from .process import ProcessOutput, ProcessRequest, SubprocessProcess

log = structlog.get_logger("health.code_health.git_sizer")

GIT_SIZER_ADAPTER_VERSION = "git-sizer-adapter-v1"
GIT_SIZER_JSON_VERSION = "2"


class GitSizerPayloadError(ValueError):
    """Raised when a git-sizer snapshot is not a JSON object."""


class GitSizerRunner(Protocol):
    def run(self, request: ProcessRequest) -> ProcessOutput: ...


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _payload(snapshot: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            raise GitSizerPayloadError("git-sizer output is not valid JSON") from exc
    if not isinstance(snapshot, Mapping):
        raise GitSizerPayloadError("git-sizer output must be a JSON object")
    return snapshot


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


_ALIASES: dict[str, frozenset[str]] = {
    "unique_ref_count": frozenset({_key(x) for x in ("uniqueRefCount", "uniqueRefs", "refs")}),
    "unique_commit_count": frozenset({_key(x) for x in ("uniqueCommitCount", "uniqueCommits", "commits")}),
    "unique_blob_count": frozenset({_key(x) for x in ("uniqueBlobCount", "uniqueBlobs", "blobs")}),
    "unique_tree_count": frozenset({_key(x) for x in ("uniqueTreeCount", "uniqueTrees", "trees")}),
    "max_blob_size": frozenset({_key(x) for x in ("maxBlobSize", "largestBlob", "largestBlobSize")}),
    "max_tree_depth": frozenset({_key(x) for x in ("maxTreeDepth", "treeDepth")}),
    "max_path_depth": frozenset({_key(x) for x in ("maxPathDepth", "pathDepth")}),
    "max_checkout_size": frozenset({_key(x) for x in ("maxCheckoutSize", "checkoutSize")}),
    "max_checkout_files": frozenset({_key(x) for x in ("maxCheckoutFiles", "checkoutFiles")}),
    "max_tree_entries": frozenset({_key(x) for x in ("maxTreeEntries", "treeEntries")}),
    "max_history_depth": frozenset({_key(x) for x in ("maxHistoryDepth", "historyDepth")}),
}

_ALIASES["unique_ref_count"] = _ALIASES["unique_ref_count"] | frozenset({_key("referenceCount")})
_ALIASES["max_path_depth"] = _ALIASES["max_path_depth"] | frozenset({_key("maxCheckoutPathDepth")})
_ALIASES["max_checkout_size"] = _ALIASES["max_checkout_size"] | frozenset({_key("maxCheckoutBlobSize")})
_ALIASES["max_checkout_files"] = _ALIASES["max_checkout_files"] | frozenset({_key("maxCheckoutBlobCount")})


def _metric_rows(value: object, path: str = "") -> list[tuple[str, Mapping[str, Any], str]]:
    """Find JSON-v2 metric objects without retaining the raw payload."""
    rows: list[tuple[str, Mapping[str, Any], str]] = []
    if isinstance(value, Mapping):
        for name, child in value.items():
            child_path = f"{path}/{name}" if path else f"/{name}"
            child_map = _mapping(child)
            if child_map is not None and ("value" in child_map or "levelOfConcern" in child_map):
                rows.append((str(name), child_map, child_path))
            rows.extend(_metric_rows(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(_metric_rows(child, f"{path}/{index}"))
    return rows


def _metric_value(row: Mapping[str, Any]) -> float | int | str | None:
    value = row.get("value", row.get("rawValue"))
    number = _number(value)
    if number is not None:
        return int(number) if number.is_integer() else number
    if value not in (None, ""):
        return str(value)
    return None


class GitSizerAdapter:
    """Normalize git-sizer output and own the only CLI invocation boundary."""

    def collect(
        self,
        context: AnalyzerContext,
        policy: CodeHealthPolicy,
        *,
        snapshot: Mapping[str, Any] | str | None = None,
        runner: GitSizerRunner | ProcessExecutor | None = None,
    ) -> GitStructureFacts:
        output: ProcessOutput | None = None
        if snapshot is None:
            executable = context.tool_paths.get("git-sizer") or context.tool_paths.get("git_sizer")
            if not executable:
                return GitStructureFacts(
                    status=CodeHealthStatus.UNAVAILABLE,
                    diagnostics={"failure_kind": "executable_missing", "process_invoked": False},
                )
            executor = runner or SubprocessProcess()
            output = executor.run(
                ProcessRequest(
                    tool_id="code-health.git-sizer",
                    executable=executable,
                    args=("--json", "--json-version=2", "--no-progress", "--verbose"),
                    cwd=context.repo_path,
                    timeout=policy.git_sizer_timeout_seconds,
                    output_cap=policy.git_sizer_output_cap_bytes,
                    repository_id=context.repo_id,
                    run_key=f"{context.repo_id}:{context.head_sha}:git-sizer",
                )
            )
            snapshot = output.stdout
        try:
            payload = _payload(snapshot or {})
            if _mapping(payload.get("error")) or payload.get("error"):
                return GitStructureFacts(
                    status=CodeHealthStatus.ERROR,
                    exit_code=output.exit_code if output else None,
                    timed_out=bool(output and output.timed_out),
                    truncated=bool(output and output.truncated),
                    diagnostics={"failure_kind": "tool_error", "process_invoked": output is not None},
                )
            metrics: dict[str, float | int | str] = {}
            concerns: dict[str, str] = {}
            evidence: list[CodeHealthEvidenceFact] = []
            for raw_name, row, pointer in _metric_rows(payload):
                normalized = next(
                    (canonical for canonical, aliases in _ALIASES.items() if _key(raw_name) in aliases),
                    None,
                )
                if normalized is None:
                    continue
                value = _metric_value(row)
                if value is None:
                    continue
                metrics[normalized] = value
                concern = row.get("levelOfConcern", row.get("level_of_concern"))
                if concern not in (None, ""):
                    concerns[normalized] = str(concern)
                subject = row.get("objectName") or row.get("objectPath") or row.get("objectDescription") or row.get("path")
                evidence.append(
                    CodeHealthEvidenceFact(
                        source="git-sizer",
                        json_pointer=pointer,
                        subject=str(subject) if subject else normalized,
                        value=value,
                        confidence=1.0,
                    )
                )
                if len(evidence) >= policy.max_findings:
                    break
            status_raw = str(payload.get("status") or "").upper()
            status = (
                CodeHealthStatus.ERROR
                if status_raw in {"ERROR", "FAILED"}
                else CodeHealthStatus.PARTIAL
                if (output and (output.exit_code not in (None, 0) or output.timed_out or output.truncated))
                else CodeHealthStatus.MEASURED
                if metrics
                else CodeHealthStatus.NOT_APPLICABLE
            )
            if output and output.timed_out:
                status = CodeHealthStatus.ERROR
            coverage = 0.5 if output and (output.truncated or output.exit_code not in (None, 0)) else 1.0 if metrics else 0.0
            confidence = 0.25 if output and output.timed_out else coverage
            return GitStructureFacts(
                status=status,
                tool_version=str(payload.get("tool_version") or payload.get("version") or "unknown"),
                json_version=str(payload.get("json_version") or payload.get("jsonVersion") or GIT_SIZER_JSON_VERSION),
                metrics=metrics,
                level_of_concern=concerns,
                evidence=tuple(evidence),
                source_snapshot_digest=str(payload.get("source_snapshot_digest") or stable_digest(payload)),
                exit_code=output.exit_code if output else 0,
                timed_out=bool(output and output.timed_out),
                truncated=bool(output and output.truncated),
                coverage=coverage,
                confidence=confidence,
                diagnostics={
                    "process_invoked": output is not None,
                    "metric_count": len(metrics),
                    "level_of_concern_count": len(concerns),
                    "stdout_duration_ms": output.duration_ms if output else None,
                },
            )
        except (TypeError, ValueError, GitSizerPayloadError) as exc:
            log.error("git_sizer_snapshot_invalid", repo_id=context.repo_id, error_type=type(exc).__name__)
            return GitStructureFacts(
                status=CodeHealthStatus.ERROR,
                exit_code=output.exit_code if output else None,
                diagnostics={"failure_kind": "malformed_snapshot", "error_type": type(exc).__name__},
            )


__all__ = [
    "GIT_SIZER_ADAPTER_VERSION",
    "GIT_SIZER_JSON_VERSION",
    "GitSizerAdapter",
    "GitSizerPayloadError",
]
