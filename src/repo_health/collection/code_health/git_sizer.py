"""git-sizer JSON-v2 adapter without vendor discovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...collection.ports import CollectionContext
from ...contracts.requests import RepositoryRef
from ...contracts.results import CodeHealthFacts, CollectionState, Limitation, RepositoryFacts, SourceStatus
from ...infrastructure.process import ProcessRequest, SubprocessProcess


class GitSizerSnapshotError(ValueError):
    pass


class GitSizerCollector:
    source_id = "git-sizer"

    def __init__(self, *, executable: str = "git-sizer", runner: Any | None = None) -> None:
        self.executable = executable
        self.runner = runner or SubprocessProcess()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        output = self.runner.run(
            ProcessRequest(
                tool_id=self.source_id,
                executable=self.executable,
                args=("--json", "--json-version=2", "--no-progress", "--verbose"),
                cwd=context.checkout_path,
                timeout=120,
                output_cap=context.limits.max_response_bytes,
                repository_id=repository.repository_id,
                phase="collect",
            )
        )
        if output.start_error:
            return _failure(repository, "git_sizer.missing", "git-sizer executable is unavailable")
        if output.timed_out:
            return _failure(
                repository,
                "git_sizer.timeout",
                "git-sizer exceeded its collection timeout",
                state=CollectionState.TIMEOUT,
            )
        if output.truncated:
            return _failure(
                repository,
                "git_sizer.output_capped",
                "git-sizer output exceeded the configured cap",
                state=CollectionState.PARTIAL,
            )
        try:
            return self.from_snapshot(repository, output.stdout)
        except GitSizerSnapshotError:
            return _failure(
                repository, "git_sizer.malformed", "git-sizer returned malformed JSON", state=CollectionState.ERROR
            )

    def from_snapshot(self, repository: RepositoryRef, snapshot: str | Mapping[str, Any]) -> RepositoryFacts:
        payload = _decode(snapshot)
        observations: list[dict[str, Any]] = []
        for key in (
            "uniqueRefCount",
            "uniqueCommitCount",
            "uniqueBlobCount",
            "maxBlobSize",
            "maxPathDepth",
            "maxCheckoutSize",
            "maxCheckoutFiles",
        ):
            value = _find(payload, key)
            if isinstance(value, (bool, dict, list)) or value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            observations.append({"key": _snake(key), "value": int(number) if number.is_integer() else number})
        if not observations:
            raise GitSizerSnapshotError("git-sizer snapshot has no supported metrics")
        group = CodeHealthFacts(available=True, observations=tuple(observations))
        status = SourceStatus(source_id=self.source_id, source_version="json-v2", state=CollectionState.AVAILABLE)
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: "json-v2"},
            source_statuses=(status,),
            code_health=group,
        )


def _decode(snapshot: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(snapshot, Mapping):
        return snapshot
    try:
        decoded = json.loads(snapshot)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GitSizerSnapshotError("git-sizer snapshot is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise GitSizerSnapshotError("git-sizer snapshot must be an object")
    return decoded


def _find(payload: Mapping[str, Any], key: str) -> Any:
    if key in payload:
        value = payload[key]
        if isinstance(value, Mapping):
            return value.get("value", value.get("rawValue"))
        return value
    for value in payload.values():
        if isinstance(value, Mapping):
            found = _find(value, key)
            if found is not None:
                return found
    return None


def _snake(value: str) -> str:
    out = ""
    for char in value:
        out += "_" + char.casefold() if char.isupper() else char
    return out.strip("_")


def _failure(
    repository: RepositoryRef, code: str, reason: str, *, state: CollectionState = CollectionState.UNAVAILABLE
) -> RepositoryFacts:
    limitation = Limitation(code=code, reason=reason)
    return RepositoryFacts(
        repository=repository,
        source_versions={"git-sizer": "unavailable"},
        source_statuses=(SourceStatus(source_id="git-sizer", state=state, limitations=(limitation,)),),
        code_health=CodeHealthFacts(limitations=(limitation,)),
        limitations=(limitation,),
    )


__all__ = ["GitSizerCollector", "GitSizerSnapshotError"]
