"""Normalize TODO/FIXME and existing Git-history debt observations."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .code_health_facts import (
    CodeHealthPolicy,
    CodeHealthStatus,
    TodoDebtFacts,
    TodoFact,
)
from .contracts import AnalyzerContext

log = structlog.get_logger("health.code_health.todo")

TODO_ADAPTER_VERSION = "todo-debt-adapter-v1"
_MARKER = re.compile(r"\b(TODO|FIXME)\b", re.IGNORECASE)
_SOURCE_EXTENSIONS = frozenset(
    {
        ".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".kt", ".m", ".php",
        ".py", ".rb", ".rs", ".scala", ".sh", ".swift", ".ts", ".tsx", ".vue", ".yaml", ".yml",
    }
)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return value if isinstance(value, Sequence) else None


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result >= 0 and result not in {float("inf"), float("-inf")} else None


def _int(value: object, default: int = 0) -> int:
    number = _number(value)
    return max(0, int(number)) if number is not None else default


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _excluded(path: str, policy: CodeHealthPolicy) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in policy.exclusions:
        candidate = pattern.replace("\\", "/").lstrip("./")
        if normalized == candidate.rstrip("/") or normalized.startswith(candidate.rstrip("/") + "/"):
            return True
        if fnmatch.fnmatchcase(normalized, candidate):
            return True
    return any(part.casefold() in {"vendor", "generated", "build", "dist", "out", "node_modules", "coverage"} for part in normalized.split("/"))


def _age_days(row: Mapping[str, Any], as_of: datetime) -> float | None:
    age = _number(row.get("age_days", row.get("ageDays")))
    if age is not None:
        return age
    created = _datetime(row.get("created_at", row.get("createdAt", row.get("introduced_at"))))
    if created is None:
        return None
    return max(0.0, (as_of - created).total_seconds() / 86400.0)


class TodoDebtAdapter:
    """Read an optional normalized history snapshot or scan source text locally."""

    def collect(
        self,
        context: AnalyzerContext,
        policy: CodeHealthPolicy,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> TodoDebtFacts:
        candidate = snapshot
        if candidate is None:
            raw = context.inventory.get("git_history_code_health")
            candidate = _mapping(raw)
        if candidate is not None:
            return self._from_snapshot(context, policy, candidate)
        git_meta_map = _mapping(context.inventory.get("git_meta_map"))
        if git_meta_map:
            return self._from_git_meta(context, policy, git_meta_map)
        source_map = context.inventory.get("code_health_source_map") or context.inventory.get("source_map")
        if isinstance(source_map, Mapping):
            return self._from_source_map(context, policy, source_map)
        return self._scan_checkout(context, policy)

    def _from_snapshot(self, context: AnalyzerContext, policy: CodeHealthPolicy, snapshot: Mapping[str, Any]) -> TodoDebtFacts:
        status_raw = str(snapshot.get("status") or "").upper().replace("-", "_")
        if status_raw in {"UNAVAILABLE", "ERROR", "NOT_APPLICABLE"}:
            status = CodeHealthStatus(status_raw)
        else:
            status = CodeHealthStatus.MEASURED
        rows = _sequence(snapshot.get("todos") or snapshot.get("markers")) or ()
        facts, todo_count, fixme_count, ages = self._rows(context, policy, rows)
        included_loc = _int(snapshot.get("included_loc", snapshot.get("loc", 0)))
        source_files = _int(snapshot.get("source_files", snapshot.get("file_count", 0)))
        excluded_files = _int(snapshot.get("excluded_files", 0))
        hotspot_rows = _sequence(snapshot.get("hotspots"))
        hotspot_count = _int(snapshot.get("hotspot_count"), len(hotspot_rows or ()))
        age_available = bool(ages) or bool(snapshot.get("age_available"))
        if status is CodeHealthStatus.MEASURED and not age_available:
            status = CodeHealthStatus.PARTIAL
        return self._build(
            status=status,
            included_loc=included_loc,
            todo_count=todo_count,
            fixme_count=fixme_count,
            ages=ages,
            facts=facts,
            hotspot_count=hotspot_count,
            source_files=source_files,
            excluded_files=excluded_files,
            confidence=1.0 if age_available else 0.65,
            coverage=1.0 if source_files or included_loc else 0.0,
            diagnostics={"source": "git_history_code_health", "age_available": age_available, "hotspot_available": "hotspots" in snapshot or "hotspot_count" in snapshot, "old_todo_days": policy.old_todo_days},
            old_todo_days=policy.old_todo_days,
        )

    def _from_git_meta(
        self,
        context: AnalyzerContext,
        policy: CodeHealthPolicy,
        git_meta_map: Mapping[str, Any],
    ) -> TodoDebtFacts:
        """Reuse the existing GitIndexer metadata and blame indexes.

        ``RepoWiseAdapter`` already pays for the FULL-tier blame walk. This
        path reads that bounded in-memory index and scans each source file once
        for marker locations; it never starts another Git subprocess.
        """
        root = Path(context.repo_path)
        source_rows: list[tuple[str, str, Mapping[str, Any]]] = []
        excluded_files = 0
        metadata_files = 0
        for raw_path, raw_meta in sorted(git_meta_map.items(), key=lambda item: str(item[0])):
            path = str(raw_path).replace("\\", "/").lstrip("./")
            if not path or _excluded(path, policy):
                excluded_files += 1
                continue
            if Path(path).suffix.casefold() not in _SOURCE_EXTENSIONS:
                continue
            metadata_files += 1
            meta = _mapping(raw_meta)
            if meta is None:
                continue
            candidate = root / Path(path)
            try:
                if not candidate.is_file() or candidate.stat().st_size > policy.max_source_file_bytes:
                    continue
                content = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            source_rows.append((path, content, meta))
            if len(source_rows) >= policy.max_source_files:
                break

        if not source_rows:
            return TodoDebtFacts(
                status=CodeHealthStatus.NOT_APPLICABLE,
                excluded_files=excluded_files,
                diagnostics={"source": "git_meta_map", "failure_kind": "no_source_files"},
            )

        rows: list[TodoFact] = []
        ages: list[float] = []
        included_loc = 0
        hotspot_count = 0
        blame_files = 0
        marker_count = 0
        aged_marker_count = 0
        todo_count = 0
        fixme_count = 0
        for path, content, meta in source_rows:
            lines = content.splitlines()
            included_loc += sum(1 for line in lines if line.strip())
            if bool(meta.get("is_hotspot")):
                hotspot_count += 1
            blame_index = meta.get("blame_index")
            blame_lines = getattr(blame_index, "lines", None)
            if isinstance(blame_lines, Mapping):
                blame_files += 1
            for line_no, line in enumerate(lines, start=1):
                match = _MARKER.search(line)
                if match is None:
                    continue
                marker = match.group(1).upper()
                marker_count += 1
                if marker == "TODO":
                    todo_count += 1
                else:
                    fixme_count += 1
                age: float | None = None
                blame_commit: str | None = None
                entry = blame_lines.get(line_no) if isinstance(blame_lines, Mapping) else None
                if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                    blame_commit = str(entry[0]) if entry[0] else None
                    try:
                        authored_at = float(entry[1])
                    except (TypeError, ValueError):
                        authored_at = 0.0
                    if authored_at > 0:
                        age = max(0.0, (context.as_of_ts.timestamp() - authored_at) / 86400.0)
                if age is not None:
                    ages.append(age)
                    aged_marker_count += 1
                if len(rows) < policy.max_findings:
                    rows.append(
                        TodoFact(
                            marker=marker,
                            path=path,
                            line=line_no,
                            age_days=age,
                            blame_commit=blame_commit,
                        )
                    )

        metadata_complete = metadata_files <= len(source_rows) and len(source_rows) < policy.max_source_files
        all_markers_aged = marker_count == 0 or aged_marker_count == marker_count
        age_available = aged_marker_count > 0
        status = CodeHealthStatus.MEASURED if metadata_complete and all_markers_aged else CodeHealthStatus.PARTIAL
        confidence = 1.0 if status is CodeHealthStatus.MEASURED else (0.8 if age_available else 0.65)
        log.info(
            "[FIX:code-health-history] reused_git_metadata",
            repo_id=context.repo_id,
            source_files=len(source_rows),
            metadata_files=metadata_files,
            blame_files=blame_files,
            marker_count=marker_count,
            aged_marker_count=aged_marker_count,
            hotspot_count=hotspot_count,
        )
        return self._build(
            status=status,
            included_loc=included_loc,
            todo_count=todo_count,
            fixme_count=fixme_count,
            ages=ages,
            facts=rows,
            hotspot_count=hotspot_count,
            source_files=len(source_rows),
            excluded_files=excluded_files,
            confidence=confidence,
            coverage=(len(source_rows) / metadata_files) if metadata_files else 0.0,
            diagnostics={
                "source": "git_meta_map",
                "age_available": age_available,
                "hotspot_available": metadata_files > 0,
                "blame_files": blame_files,
                "aged_marker_count": aged_marker_count,
                "marker_count": marker_count,
                "old_todo_days": policy.old_todo_days,
            },
            old_todo_days=policy.old_todo_days,
        )

    def _from_source_map(self, context: AnalyzerContext, policy: CodeHealthPolicy, source_map: Mapping[str, Any]) -> TodoDebtFacts:
        rows: list[TodoFact] = []
        loc = 0
        files = 0
        excluded = 0
        for raw_path, raw_content in sorted(source_map.items(), key=lambda item: str(item[0])):
            path = str(raw_path).replace("\\", "/")
            if _excluded(path, policy):
                excluded += 1
                continue
            if not isinstance(raw_content, str):
                continue
            if len(raw_content.encode("utf-8", errors="replace")) > policy.max_source_file_bytes:
                continue
            files += 1
            loc += sum(1 for line in raw_content.splitlines() if line.strip())
            for line_no, line in enumerate(raw_content.splitlines(), start=1):
                match = _MARKER.search(line)
                if match:
                    rows.append(TodoFact(marker=match.group(1).upper(), path=path, line=line_no))
            if files >= policy.max_source_files:
                break
        return self._build(
            status=CodeHealthStatus.PARTIAL,
            included_loc=loc,
            todo_count=sum(item.marker == "TODO" for item in rows),
            fixme_count=sum(item.marker == "FIXME" for item in rows),
            ages=(),
            facts=tuple(rows[: policy.max_findings]),
            hotspot_count=0,
            source_files=files,
            excluded_files=excluded,
            confidence=0.65,
            coverage=1.0 if files else 0.0,
            diagnostics={"source": "code_health_source_map", "age_available": False, "hotspot_available": False, "old_todo_days": policy.old_todo_days},
            old_todo_days=policy.old_todo_days,
        )

    def _scan_checkout(self, context: AnalyzerContext, policy: CodeHealthPolicy) -> TodoDebtFacts:
        source_map: dict[str, str] = {}
        root = Path(context.repo_path)
        if not root.exists():
            return TodoDebtFacts(status=CodeHealthStatus.UNAVAILABLE, diagnostics={"failure_kind": "checkout_missing"})
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in _SOURCE_EXTENSIONS:
                continue
            relative = path.relative_to(root).as_posix()
            if _excluded(relative, policy):
                continue
            try:
                if path.stat().st_size > policy.max_source_file_bytes:
                    continue
                source_map[relative] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(source_map) >= policy.max_source_files:
                break
        if not source_map:
            return TodoDebtFacts(status=CodeHealthStatus.NOT_APPLICABLE, diagnostics={"failure_kind": "no_source_files"})
        return self._from_source_map(context, policy, source_map)

    def _rows(self, context: AnalyzerContext, policy: CodeHealthPolicy, rows: Sequence[object]) -> tuple[tuple[TodoFact, ...], int, int, tuple[float, ...]]:
        facts: list[TodoFact] = []
        ages: list[float] = []
        todo_count = 0
        fixme_count = 0
        for raw in rows:
            row = _mapping(raw)
            if row is None:
                continue
            marker = str(row.get("marker", row.get("kind", "TODO"))).upper()
            if marker not in {"TODO", "FIXME"}:
                continue
            path = str(row.get("path", row.get("file", ""))).replace("\\", "/")
            if not path or _excluded(path, policy):
                continue
            line = _int(row.get("line", row.get("line_number", 1)), 1)
            age = _age_days(row, context.as_of_ts)
            if age is not None:
                ages.append(age)
            facts.append(TodoFact(marker=marker, path=path, line=max(1, line), age_days=age, blame_commit=str(row.get("blame_commit")) if row.get("blame_commit") else None))
            todo_count += marker == "TODO"
            fixme_count += marker == "FIXME"
            if len(facts) >= policy.max_findings:
                break
        return tuple(facts), todo_count, fixme_count, tuple(ages)

    @staticmethod
    def _build(*, status: CodeHealthStatus, included_loc: int, todo_count: int, fixme_count: int, ages: Sequence[float], facts: Sequence[TodoFact], hotspot_count: int, source_files: int, excluded_files: int, confidence: float, coverage: float, diagnostics: Mapping[str, Any], old_todo_days: int) -> TodoDebtFacts:
        total = todo_count + fixme_count
        old_count = sum(age >= old_todo_days for age in ages)
        return TodoDebtFacts(
            status=status,
            included_loc=included_loc,
            todo_count=todo_count,
            fixme_count=fixme_count,
            density_per_kloc=(total / (included_loc / 1000.0)) if included_loc else None,
            old_count=old_count,
            old_ratio=(old_count / len(ages)) if ages else None,
            ages_days=tuple(ages),
            facts=tuple(facts),
            hotspot_count=hotspot_count,
            source_files=source_files,
            excluded_files=excluded_files,
            coverage=coverage,
            confidence=confidence,
            diagnostics=diagnostics,
        )


__all__ = ["TODO_ADAPTER_VERSION", "TodoDebtAdapter"]
