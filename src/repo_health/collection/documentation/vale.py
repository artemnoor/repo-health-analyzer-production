"""Vale CLI/snapshot adapter with bounded normalized output."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...collection.ports import CollectionContext
from ...contracts.requests import RepositoryRef
from ...contracts.results import CollectionState, DocumentationFacts, Limitation, RepositoryFacts, SourceStatus
from ...infrastructure.process import ProcessRequest, SubprocessProcess


class ValeSnapshotError(ValueError):
    pass


class ValeCollector:
    source_id = "vale"

    def __init__(
        self,
        *,
        executable: str = "vale",
        config_path: str | Path | None = None,
        runner: Any | None = None,
    ) -> None:
        self.executable = executable
        self.config_path = str(config_path) if config_path else None
        self.runner = runner or SubprocessProcess()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        args = ("--output=JSON", ".")
        if self.config_path:
            args = (f"--config={self.config_path}", *args)
        output = self.runner.run(
            ProcessRequest(
                tool_id=self.source_id,
                executable=self.executable,
                args=args,
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
            analyzed_files, discovered_files, scan_truncated = _documentation_inventory(
                context.checkout_path, context.limits.max_files
            )
            return self.from_snapshot(
                repository,
                output.stdout,
                source_version="vale-cli",
                analyzed_files=analyzed_files,
                discovered_files=discovered_files,
                scan_truncated=scan_truncated,
            )
        except ValeSnapshotError:
            return self._unavailable(
                repository, "vale.malformed", "Vale returned malformed JSON", state=CollectionState.ERROR
            )

    def from_snapshot(
        self,
        repository: RepositoryRef,
        snapshot: str | Mapping[str, Any],
        *,
        source_version: str,
        analyzed_files: tuple[Path, ...] = (),
        discovered_files: int | None = None,
        scan_truncated: bool = False,
    ) -> RepositoryFacts:
        payload = _decode(snapshot)
        findings = _findings(payload)
        if not isinstance(findings, (list, tuple)):
            raise ValeSnapshotError("Vale findings must be a list")
        files = {str(_field(item, "file", "File")) for item in findings if _field(item, "file", "File")}
        file_count = len(analyzed_files) or len(files)
        discovered_count = max(file_count, discovered_files if discovered_files is not None else file_count)
        observations: list[dict[str, Any]] = [
            {"key": "finding_count", "value": len(findings)},
            {"key": "file_count", "value": file_count},
            {"key": "discovered_files", "value": discovered_count},
            {
                "key": "error_count",
                "value": sum(
                    str(_field(item, "severity", "Severity") or "").casefold() in {"error", "fatal"}
                    for item in findings
                    if isinstance(item, Mapping)
                ),
            },
        ]
        observations.extend(_finding_observations(findings))
        if analyzed_files:
            observations.extend(_documentation_surface_observations(analyzed_files, discovered_count))
        group = DocumentationFacts(
            available=True,
            observations=tuple(observations),
            limitations=(
                (Limitation(code="vale.scan_capped", reason="Documentation scan reached the configured file limit"),)
                if scan_truncated
                else ()
            ),
        )
        state = CollectionState.PARTIAL if scan_truncated else CollectionState.AVAILABLE
        status = SourceStatus(
            source_id=self.source_id,
            source_version=source_version,
            state=state,
            limitations=group.limitations,
        )
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: source_version},
            source_statuses=(status,),
            documentation=group,
            limitations=group.limitations,
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


def _findings(payload: Mapping[str, Any] | list[Any]) -> list[Mapping[str, Any]]:
    """Normalize Vale's file-keyed JSON and the compact test snapshot shape."""

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    explicit = payload.get("findings") or payload.get("violations")
    if isinstance(explicit, list):
        return [item for item in explicit if isinstance(item, Mapping)]
    findings: list[Mapping[str, Any]] = []
    for relative_path, entries in payload.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, Mapping):
                findings.append({"file": relative_path, **entry})
    return findings


def _field(item: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


_DOCUMENTATION_SUFFIXES = frozenset({".adoc", ".asciidoc", ".dita", ".md", ".mdx", ".rst", ".txt"})
_EXCLUDED_PARTS = frozenset({".git", "build", "dist", "node_modules", "vendor"})
_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_INSTRUCTION_MARKERS = (
    re.compile(r"\b(?:getting started|installation|install|setup|usage|quickstart|quick start)\b", re.I),
    re.compile(r"\b(?:configuration|configure|environment variables?|deployment|deploy|run|launch)\b", re.I),
    re.compile(r"(?:pip|uv|npm|pnpm|yarn)\s+install\b|docker\s+(?:run|compose)\b", re.I),
)


def _documentation_inventory(root: Path, limit: int) -> tuple[tuple[Path, ...], int, bool]:
    if not root.is_dir():
        return (), 0, False
    files = (
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix.casefold() in _DOCUMENTATION_SUFFIXES
        and not any(part.casefold() in _EXCLUDED_PARTS for part in path.relative_to(root).parts)
    )
    all_files = tuple(files)
    return all_files[:limit], len(all_files), len(all_files) > limit


def _finding_observations(findings: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts = {"suggestion": 0, "warning": 0, "error": 0, "fatal": 0}
    for item in findings:
        severity = str(_field(item, "severity", "Severity") or "").casefold()
        if severity in counts:
            counts[severity] += 1
    weighted = counts["suggestion"] * 0.25 + counts["warning"] + counts["error"] * 2.0 + counts["fatal"] * 3.0
    return [{"key": f"{name}_count", "value": value} for name, value in counts.items()] + [
        {"key": "weighted_finding_points", "value": weighted}
    ]


def _documentation_surface_observations(files: tuple[Path, ...], discovered_count: int) -> list[dict[str, Any]]:
    relative_paths = tuple(path.as_posix() for path in files)
    flags = {
        "readme_present": any(Path(path).name.casefold().startswith("readme") for path in relative_paths),
        "docs_directory_present": any(path.casefold().split("/")[0] == "docs" for path in relative_paths),
        "contributing_present": any(Path(path).name.casefold().startswith("contributing") for path in relative_paths),
        "changelog_present": any(
            Path(path).name.casefold().startswith(("changelog", "history")) for path in relative_paths
        ),
        "license_present": any(Path(path).name.casefold().startswith("license") for path in relative_paths),
        "api_docs_present": any(
            any(token in path.casefold() for token in ("api", "reference", "architecture")) for path in relative_paths
        ),
    }
    words = complex_words = long_words = 0
    instruction_sections = 0
    readme_words = 0
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tokens = _WORD.findall(content)
        words += len(tokens)
        complex_words += sum(len(token) >= 8 for token in tokens)
        long_words += sum(len(token) >= 12 for token in tokens)
        instruction_sections += sum(bool(pattern.search(content)) for pattern in _INSTRUCTION_MARKERS)
        if path.name.casefold().startswith("readme"):
            readme_words += len(tokens)
    artifact_count = sum(flags.values())
    surface_ratio = min(1.0, artifact_count / 6.0)
    content_ratio = min(1.0, words / 500.0)
    scan_ratio = min(1.0, len(files) / max(discovered_count, 1))
    completeness = 100.0 * scan_ratio * (0.40 + 0.40 * surface_ratio + 0.20 * content_ratio)
    instructions = min(100.0, instruction_sections * 25.0)
    readability = max(
        0.0,
        100.0 - 100.0 * complex_words / max(words, 1) - 60.0 * long_words / max(words, 1),
    )
    return [
        {"key": "analyzed_files", "value": len(files)},
        {"key": "words", "value": words},
        {"key": "readme_words", "value": readme_words},
        {"key": "complex_words", "value": complex_words},
        {"key": "long_words", "value": long_words},
        {"key": "instruction_section_count", "value": instruction_sections},
        {"key": "has_instructions", "value": instruction_sections > 0},
        {"key": "instructions", "value": instructions},
        {"key": "completeness", "value": completeness},
        {"key": "readability", "value": readability},
        *[{"key": key, "value": value} for key, value in flags.items()],
    ]


__all__ = ["ValeCollector", "ValeSnapshotError"]
