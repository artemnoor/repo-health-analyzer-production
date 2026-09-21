"""Bounded PyDriller adapter producing normalized Git facts only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog

from ...collection.ports import CollectionContext
from ...contracts.requests import RepositoryRef
from ...contracts.results import CollectionState, GitFacts, Limitation, RepositoryFacts, SourceStatus

log = structlog.get_logger("repo_health.collection.git.pydriller")


class PyDrillerCollector:
    source_id = "pydriller"

    def __init__(self, *, max_commits: int = 50_000) -> None:
        if max_commits <= 0:
            raise ValueError("max_commits must be positive")
        self.max_commits = max_commits

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        try:
            from pydriller import Repository
        except ImportError:
            return self._unavailable(repository, "pydriller.missing", "PyDriller is not installed")
        root = Path(context.checkout_path).resolve()
        if not root.is_dir():
            return self._unavailable(repository, "pydriller.checkout_missing", "Git checkout is unavailable")
        commits = 0
        authors: set[str] = set()
        latest: datetime | None = None
        try:
            for commit in Repository(str(root), only_in_branch=repository.ref).traverse_commits():
                commits += 1
                author = getattr(getattr(commit, "author", None), "name", None)
                if author:
                    authors.add(str(author).strip().casefold()[:128])
                authored_date = getattr(commit, "author_date", None)
                if isinstance(authored_date, datetime):
                    candidate = authored_date.replace(tzinfo=authored_date.tzinfo or UTC).astimezone(UTC)
                    latest = max(latest, candidate) if latest else candidate
                if commits >= min(context.limits.max_commits, self.max_commits):
                    break
        except Exception as exc:
            log.warning(
                "pydriller_collection_failed", repository_id=repository.repository_id, error_type=type(exc).__name__
            )
            return self._unavailable(repository, "pydriller.collection_error", "PyDriller traversal failed")
        observations = [
            {"key": "commit_count", "value": commits},
            {"key": "author_count", "value": len(authors)},
            {"key": "history_complete", "value": commits < min(context.limits.max_commits, self.max_commits)},
        ]
        if latest:
            observations.append({"key": "latest_activity_at", "value": latest.isoformat()})
        limitation = (
            Limitation(code="pydriller.history_capped", reason="history was bounded by collection limits")
            if commits >= min(context.limits.max_commits, self.max_commits)
            else None
        )
        state = CollectionState.PARTIAL if limitation else CollectionState.AVAILABLE
        status = SourceStatus(
            source_id=self.source_id,
            state=state,
            source_version="2.12",
            limitations=(limitation,) if limitation else (),
        )
        return RepositoryFacts(
            repository=repository,
            source_versions={self.source_id: "2.12"},
            source_statuses=(status,),
            git=GitFacts(
                available=commits > 0, observations=tuple(observations), limitations=(limitation,) if limitation else ()
            ),
            limitations=(limitation,) if limitation else (),
        )

    @staticmethod
    def _unavailable(repository: RepositoryRef, code: str, reason: str) -> RepositoryFacts:
        limitation = Limitation(code=code, reason=reason)
        return RepositoryFacts(
            repository=repository,
            source_versions={"pydriller": "unavailable"},
            source_statuses=(
                SourceStatus(source_id="pydriller", state=CollectionState.UNAVAILABLE, limitations=(limitation,)),
            ),
            limitations=(limitation,),
        )


__all__ = ["PyDrillerCollector"]
