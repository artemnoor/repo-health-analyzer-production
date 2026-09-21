"""Vale CLI/snapshot adapter with bounded normalized output."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...collection.ports import CollectionContext
from ...contracts.requests import RepositoryRef
from ...contracts.results import CollectionState, DocumentationFacts, Limitation, RepositoryFacts, SourceStatus
from ...infrastructure.process import ProcessRequest, SubprocessProcess


class ValeSnapshotError(ValueError):
    pass


class ValeCollector:
    source_id = "vale"

    def __init__(self, *, executable: str = "vale", runner: Any | None = None) -> None:
        self.executable = executable
        self.runner = runner or SubprocessProcess()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        output = self.runner.run(
            ProcessRequest(
                tool_id=self.source_id,
                executable=self.executable,
                args=("--output=JSON", "."),
                cwd=context.checkout_path,
                timeout=120,
                output_cap=context.limits.max_response_bytes,
                repository_id=repository.repository_id,
                phase="collect",
            )
        )
        if output.start_error:
            return self._unavailable(repository, "vale.missing", "Vale executable is unavailable")
        if output.timed_out:
            return self._unavailable(
                repository, "vale.timeout", "Vale exceeded its collection timeout", state=CollectionState.TIMEOUT
            )
        if output.truncated:
            return self._unavailable(
                repository,
                "vale.output_capped",
                "Vale output exceeded the configured cap",
                state=CollectionState.PARTIAL,
            )
        try:
            return self.from_snapshot(repository, output.stdout, source_version="vale-cli")
        except ValeSnapshotError:
            return self._unavailable(
                repository, "vale.malformed", "Vale returned malformed JSON", state=CollectionState.ERROR
            )

    def from_snapshot(
        self, repository: RepositoryRef, snapshot: str | Mapping[str, Any], *, source_version: str
    ) -> RepositoryFacts:
        payload = _decode(snapshot)
        rows = payload if isinstance(payload, Mapping) else {"findings": payload}
        findings = rows.get("findings") or rows.get("violations") or ()
        if not isinstance(findings, (list, tuple)):
            raise ValeSnapshotError("Vale findings must be a list")
        files = {str(item.get("file")) for item in findings if isinstance(item, Mapping) and item.get("file")}
        group = DocumentationFacts(
            available=True,
            observations=(
                {"key": "finding_count", "value": len(findings)},
                {"key": "file_count", "value": len(files)},
                {
                    "key": "error_count",
                    "value": sum(
                        str(item.get("severity", "")).casefold() in {"error", "fatal"}
                        for item in findings
                        if isinstance(item, Mapping)
                    ),
                },
            ),
        )
        status = SourceStatus(source_id=self.source_id, source_version=source_version, state=CollectionState.AVAILABLE)
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: source_version},
            source_statuses=(status,),
            documentation=group,
        )

    @staticmethod
    def _unavailable(
        repository: RepositoryRef, code: str, reason: str, *, state: CollectionState = CollectionState.UNAVAILABLE
    ) -> RepositoryFacts:
        limitation = Limitation(code=code, reason=reason)
        return RepositoryFacts(
            repository=repository,
            source_versions={"vale": "unavailable"},
            source_statuses=(SourceStatus(source_id="vale", state=state, limitations=(limitation,)),),
            documentation=DocumentationFacts(limitations=(limitation,)),
            limitations=(limitation,),
        )


def _decode(snapshot: str | Mapping[str, Any]) -> Mapping[str, Any] | list[Any]:
    if isinstance(snapshot, Mapping):
        return snapshot
    try:
        decoded = json.loads(snapshot)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValeSnapshotError("Vale snapshot is not valid JSON") from exc
    if not isinstance(decoded, (Mapping, list)):
        raise ValeSnapshotError("Vale snapshot must be an object or list")
    return decoded


__all__ = ["ValeCollector", "ValeSnapshotError"]
