"""Bounded TODO/FIXME scan over an explicit checkout."""

from __future__ import annotations

import re
from pathlib import Path

from ...collection.ports import CollectionContext
from ...contracts.requests import RepositoryRef
from ...contracts.results import CodeHealthFacts, CollectionState, Limitation, RepositoryFacts, SourceStatus

_MARKER = re.compile(r"\b(TODO|FIXME)\b", re.I)
_EXTENSIONS = frozenset(
    {
        ".c",
        ".cpp",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".swift",
        ".ts",
        ".tsx",
        ".vue",
        ".yaml",
        ".yml",
    }
)
_EXCLUDED = frozenset({"vendor", "node_modules", "dist", "build", "generated", ".git"})


class TodoHistoryCollector:
    source_id = "git.todo-history"

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        root = Path(context.checkout_path).resolve()
        if not root.is_dir():
            limitation = Limitation(code="todo.checkout_missing", reason="Git checkout is unavailable")
            return RepositoryFacts(
                repository=repository,
                source_statuses=(
                    SourceStatus(
                        source_id=self.source_id, state=CollectionState.UNAVAILABLE, limitations=(limitation,)
                    ),
                ),
                code_health=CodeHealthFacts(limitations=(limitation,)),
                limitations=(limitation,),
            )
        todo = fixme = files = 0
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or path.suffix.casefold() not in _EXTENSIONS
                or any(part.casefold() in _EXCLUDED for part in path.relative_to(root).parts)
            ):
                continue
            files += 1
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            todo += sum(match.group(1).upper() == "TODO" for match in _MARKER.finditer(content))
            fixme += sum(match.group(1).upper() == "FIXME" for match in _MARKER.finditer(content))
            if files >= context.limits.max_files:
                break
        group = CodeHealthFacts(
            available=files > 0,
            observations=(
                {"key": "source_file_count", "value": files},
                {"key": "todo_count", "value": todo},
                {"key": "fixme_count", "value": fixme},
            ),
        )
        status = SourceStatus(
            source_id=self.source_id, state=CollectionState.AVAILABLE if files else CollectionState.PARTIAL
        )
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: "local-scan-v1"},
            source_statuses=(status,),
            code_health=group,
        )


__all__ = ["TodoHistoryCollector"]
