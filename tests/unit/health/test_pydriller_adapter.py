"""Unit coverage for the normalized PyDriller adapter boundary."""

from __future__ import annotations

import subprocess
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext
from repowise.core.analysis.health.integrations.pydriller_adapter import (
    FailureKind,
    GitActivityBaseline,
    PyDrillerAdapter,
    PyDrillerExecutionStatus,
    load_pydriller_policy,
)

ROOT = Path(__file__).resolve().parents[3]


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(path: Path) -> None:
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "one@example.test")
    _git(path, "config", "user.name", "One Author")


def _commit(path: Path, relative: str, content: str, message: str, *, allow_empty: bool = False) -> str:
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(path, "add", relative)
    args = ["commit", "-q", "-m", message]
    if allow_empty:
        args.insert(1, "--allow-empty")
    _git(path, *args)
    return _git(path, "rev-parse", "HEAD")


def _context(path: Path, *, scope: str | None = None) -> AnalyzerContext:
    head = "empty-repository"
    if (path / ".git").exists():
        with suppress(subprocess.CalledProcessError):
            head = _git(path, "rev-parse", "HEAD")
    inventory: dict[str, Any] = {"default_branch": "main"}
    if scope:
        inventory["pydriller_scope"] = scope
    return AnalyzerContext(
        repo_path=path,
        repo_id=f"test:{path.name}",
        head_sha=head,
        as_of_ts=datetime(2026, 9, 18, tzinfo=UTC),
        inventory=inventory,
    )


def test_normal_history_is_normalized_without_diff_access(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "README.md", "one\n", "initial")
    _commit(tmp_path, "README.md", "one\ntwo\n", "update")

    facts = PyDrillerAdapter().collect(_context(tmp_path))

    assert facts.execution_status is PyDrillerExecutionStatus.MEASURED
    assert facts.unique_commit_count == 2
    assert facts.total_additions == 2
    assert facts.total_deletions == 0
    assert facts.total_churn == 2
    assert facts.tracked_unique_file_count == 1
    assert facts.history_complete is True
    assert facts.sample_commit_hashes == tuple(sorted(facts.sample_commit_hashes))


def test_duplicate_local_refs_are_counted_once(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "initial")
    _commit(tmp_path, "module.py", "two\n", "update")
    _git(tmp_path, "branch", "duplicate")

    facts = PyDrillerAdapter().collect(_context(tmp_path, scope="all_local_refs"))

    assert facts.resolved_refs == ("duplicate", "main")
    assert facts.unique_commit_count == 2
    assert facts.commit_occurrence_count == 4
    assert facts.duplicate_commit_count == 2
    assert facts.total_churn == 3


def test_empty_commit_is_retained_as_activity_with_zero_churn(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "initial")
    _commit(tmp_path, "module.py", "one\n", "empty", allow_empty=True)

    facts = PyDrillerAdapter().collect(_context(tmp_path))

    assert facts.unique_commit_count == 2
    assert facts.empty_commit_count == 1
    assert facts.total_churn == 1
    assert any(commit.is_empty for commit in facts.recent_commits)


def test_merge_commit_is_not_silently_dropped(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "base.txt", "base\n", "base")
    _git(tmp_path, "checkout", "-q", "-b", "side")
    _commit(tmp_path, "side.txt", "side\n", "side")
    _git(tmp_path, "checkout", "-q", "main")
    _commit(tmp_path, "main.txt", "main\n", "main")
    _git(tmp_path, "merge", "--no-ff", "-q", "side", "-m", "merge side")

    facts = PyDrillerAdapter().collect(_context(tmp_path))

    assert facts.execution_status is PyDrillerExecutionStatus.MEASURED
    assert facts.merge_commit_count == 1
    assert facts.empty_commit_count == 0
    assert facts.unique_commit_count == 4


def test_empty_repository_is_no_activity(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")

    facts = PyDrillerAdapter().collect(_context(tmp_path))

    assert facts.execution_status is PyDrillerExecutionStatus.NO_ACTIVITY
    assert facts.unique_commit_count == 0
    assert facts.coverage == 0


def test_missing_and_invalid_repository_states_are_distinct(tmp_path: Path) -> None:
    missing = PyDrillerAdapter().collect(_context(tmp_path / "missing"))
    invalid_path = tmp_path / "not-a-repository"
    invalid_path.mkdir()
    invalid = PyDrillerAdapter().collect(_context(invalid_path))

    assert missing.execution_status is PyDrillerExecutionStatus.UNAVAILABLE
    assert missing.failure_kind is FailureKind.MISSING_REPOSITORY
    assert invalid.execution_status is PyDrillerExecutionStatus.ERROR
    assert invalid.failure_kind is FailureKind.INVALID_REPOSITORY


def test_shallow_history_is_measured_with_reduced_confidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _init_repo(source)
    _commit(source, "module.py", "one\n", "one")
    _commit(source, "module.py", "two\n", "two")
    _commit(source, "module.py", "three\n", "three")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-local", str(source), str(shallow)],
        check=True,
        capture_output=True,
        text=True,
    )

    facts = PyDrillerAdapter().collect(_context(shallow))

    assert facts.execution_status is PyDrillerExecutionStatus.MEASURED
    assert facts.history_is_shallow is True
    assert facts.history_complete is False
    assert facts.confidence <= 0.70


def test_multiple_authors_are_aggregated_without_raw_emails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "one.py", "one\n", "one")
    _git(tmp_path, "config", "user.email", "two@example.test")
    _git(tmp_path, "config", "user.name", "Two Author")
    _commit(tmp_path, "two.py", "two\n", "two")

    facts = PyDrillerAdapter().collect(_context(tmp_path))

    assert facts.unique_author_count == 2
    assert len(facts.contributors) == 2
    assert all("@" not in contributor.identity_key for contributor in facts.contributors)
    assert all("@" not in str(contributor) for contributor in facts.contributors)


def test_result_is_deterministic_except_duration(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "one")
    _commit(tmp_path, "module.py", "two\n", "two")
    context = _context(tmp_path)

    first = PyDrillerAdapter().collect(context)
    second = PyDrillerAdapter().collect(context)

    assert first.summary() == second.summary()
    assert first.contributors == second.contributors
    assert first.windows == second.windows
    assert first.buckets == second.buckets
    assert first.file_histories == second.file_histories


def test_missing_pydriller_is_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "one")
    original_import = __import__("builtins").__import__

    def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pydriller":
            raise ModuleNotFoundError("blocked for test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    facts = PyDrillerAdapter().collect(_context(tmp_path))

    assert facts.execution_status is PyDrillerExecutionStatus.UNAVAILABLE
    assert facts.failure_kind is FailureKind.MISSING_DEPENDENCY


def test_policy_loader_failure_is_a_policy_error(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "one")

    facts = PyDrillerAdapter(policy_loader=lambda: (_ for _ in ()).throw(ValueError("malformed"))).collect(
        _context(tmp_path)
    )

    assert facts.execution_status is PyDrillerExecutionStatus.ERROR
    assert facts.failure_kind is FailureKind.POLICY_ERROR


def test_timeout_is_normalized_to_error(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "one")

    def timeout_factory(_path: str, **_kwargs: Any) -> Any:
        raise TimeoutError("synthetic timeout")

    facts = PyDrillerAdapter(repository_factory=timeout_factory).collect(_context(tmp_path))

    assert facts.execution_status is PyDrillerExecutionStatus.ERROR
    assert facts.failure_kind is FailureKind.TIMEOUT


def test_baseline_overlap_is_measured_without_adding_source_counts(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    first_hash = _commit(tmp_path, "module.py", "one\n", "one")
    second_hash = _commit(tmp_path, "module.py", "two\n", "two")
    baseline = GitActivityBaseline(source="sourcecraft.git", commit_hashes=frozenset({first_hash}))

    facts = PyDrillerAdapter().collect(_context(tmp_path), baseline=baseline)

    assert facts.baseline_source == "sourcecraft.git"
    assert facts.overlap_status == "measured"
    assert facts.overlap_commit_count == 1
    assert facts.new_commit_count == 1
    assert second_hash in facts.sample_commit_hashes


def test_adapter_never_requests_diff_or_message_fields(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "one")

    actor = SimpleNamespace(name="Author", email="author@example.test")

    class Modification:
        new_path = "module.py"
        old_path = None
        added_lines = 1
        deleted_lines = 0
        change_type = "ADD"

        @property
        def diff(self) -> str:
            raise AssertionError("diff must not be accessed")

    commit = SimpleNamespace(
        hash="a" * 40,
        author_date=datetime(2026, 9, 17, tzinfo=UTC),
        committer_date=datetime(2026, 9, 17, tzinfo=UTC),
        author=actor,
        committer=actor,
        modified_files=(Modification(),),
        merge=False,
    )

    class FakeRepository:
        def traverse_commits(self) -> list[Any]:
            return [commit]

    facts = PyDrillerAdapter(repository_factory=lambda _path, **_kwargs: FakeRepository()).collect(
        _context(tmp_path), policy=load_pydriller_policy(ROOT)
    )

    assert facts.execution_status is PyDrillerExecutionStatus.MEASURED
    assert facts.total_churn == 1
