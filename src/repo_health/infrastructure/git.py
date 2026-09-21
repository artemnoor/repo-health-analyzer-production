"""Explicit checkout and Git collection ports; no repository discovery."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

import structlog

from ..collection.ports import CollectionContext, CollectionError
from ..contracts.requests import RepositoryRef
from ..contracts.results import CollectionState, GitFacts, Limitation, RepositoryFacts, SourceStatus
from .process import ProcessOutput, ProcessRequest, SubprocessProcess

log = structlog.get_logger("repo_health.infrastructure.git")


class CheckoutPort(Protocol):
    def path_for(self, repository: RepositoryRef, *, context: CollectionContext) -> Path: ...


class ExplicitCheckout:
    """Use only the path supplied by the execution composition root."""

    def path_for(self, repository: RepositoryRef, *, context: CollectionContext) -> Path:
        path = context.checkout_path.resolve()
        if not path.is_dir():
            raise CollectionError(f"checkout does not exist for {repository.repository_id}")
        return path


class GitRunner(Protocol):
    def run(self, request: ProcessRequest) -> ProcessOutput: ...


class GitCollector:
    source_id = "git"

    def __init__(self, *, runner: GitRunner | None = None, checkout: CheckoutPort | None = None) -> None:
        self.runner = runner or SubprocessProcess()
        self.checkout = checkout or ExplicitCheckout()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        root = self.checkout.path_for(repository, context=context)
        head = self._run(root, ("rev-parse", "HEAD"), context=context).stdout.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", head):
            return self._failure(repository, "git.invalid_head", "Git did not return an immutable head")
        count_output = self._run(root, ("rev-list", "--count", repository.ref), context=context)
        commit_count = _int(count_output.stdout)
        branch_output = self._run(root, ("symbolic-ref", "--short", "-q", "HEAD"), context=context)
        branch = branch_output.stdout.strip() or repository.ref
        observations = {
            "head_sha": head,
            "ref": branch[:255],
            "commit_count": commit_count,
        }
        group = GitFacts(
            available=True,
            observations=tuple({"key": key, "value": value} for key, value in observations.items()),
        )
        status = SourceStatus(
            source_id=self.source_id,
            state=CollectionState.AVAILABLE,
            source_version="git-cli",
        )
        return RepositoryFacts(
            repository=repository, source_versions={self.source_id: "git-cli"}, source_statuses=(status,), git=group
        )

    def _run(self, root: Path, args: tuple[str, ...], *, context: CollectionContext) -> ProcessOutput:
        output = self.runner.run(
            ProcessRequest(
                tool_id="git",
                executable="git",
                args=args,
                cwd=root,
                timeout=30,
                output_cap=context.limits.max_response_bytes,
                repository_id=context.request.repository.repository_id,
                phase="collect",
            )
        )
        if output.start_error or output.timed_out or output.truncated or output.exit_code not in (0, None):
            raise CollectionError("git command did not complete")
        return output

    @staticmethod
    def _failure(repository: RepositoryRef, code: str, reason: str) -> RepositoryFacts:
        limitation = Limitation(code=code, reason=reason)
        return RepositoryFacts(
            repository=repository,
            source_versions={"git": "git-cli"},
            source_statuses=(SourceStatus(source_id="git", state=CollectionState.ERROR, limitations=(limitation,)),),
            limitations=(limitation,),
        )


def _int(value: str) -> int:
    try:
        return max(0, int(value.strip()))
    except (TypeError, ValueError):
        return 0


__all__ = ["CheckoutPort", "ExplicitCheckout", "GitCollector", "GitRunner"]
