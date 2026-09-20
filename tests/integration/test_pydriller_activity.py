"""Real local-Git integration coverage for Activity + PyDriller."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.chaoss_adapter import activity_adapter


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init(path: Path) -> None:
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "one@example.test")
    _git(path, "config", "user.name", "One")


def _commit(path: Path, name: str, content: str, message: str) -> str:
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(path, "add", name)
    _git(path, "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def _context(path: Path, *, inventory: dict[str, object] | None = None) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=path,
        repo_id=f"integration:{path.name}",
        head_sha=_git(path, "rev-parse", "HEAD"),
        as_of_ts=datetime(2026, 9, 18, tzinfo=UTC),
        inventory={"default_branch": "main", **(inventory or {})},
        capabilities=("chaoss:events", "git", "local_scan"),
    )


def _metric(result: object, name: str) -> object:
    return next(metric for metric in result.metrics if metric.name == name)  # type: ignore[attr-defined]


def test_activity_adapter_adds_real_pydriller_history(tmp_path: Path) -> None:
    _init(tmp_path)
    _commit(tmp_path, "README.md", "one\n", "one")
    _commit(tmp_path, "README.md", "one\ntwo\n", "two")

    result = activity_adapter(_context(tmp_path))

    assert result.status is AnalyzerStatus.PASS
    assert result.score is not None
    assert _metric(result, "pydriller:unique_commits").value == 2
    assert _metric(result, "pydriller:activity_quality").denominator == 1
    assert result.diagnostics["pydriller_status"] == "MEASURED"
    assert result.source_versions["pydriller"] == "2.12"


def test_activity_adapter_deduplicates_multiple_local_refs(tmp_path: Path) -> None:
    _init(tmp_path)
    _commit(tmp_path, "module.py", "one\n", "one")
    _commit(tmp_path, "module.py", "two\n", "two")
    _git(tmp_path, "branch", "review")

    result = activity_adapter(
        _context(tmp_path, inventory={"pydriller_scope": "all_local_refs"})
    )

    pydriller = result.diagnostics["pydriller"]
    assert pydriller["ref_scope"] == "all_local_refs"
    assert pydriller["unique_commit_count"] == 2
    assert pydriller["duplicate_commit_count"] == 2
    assert pydriller["total_churn"] == 3


def test_activity_adapter_reports_merge_and_multiple_authors(tmp_path: Path) -> None:
    _init(tmp_path)
    _commit(tmp_path, "base.txt", "base\n", "base")
    _git(tmp_path, "checkout", "-q", "-b", "side")
    _git(tmp_path, "config", "user.email", "two@example.test")
    _git(tmp_path, "config", "user.name", "Two")
    _commit(tmp_path, "side.txt", "side\n", "side")
    _git(tmp_path, "checkout", "-q", "main")
    _git(tmp_path, "config", "user.email", "one@example.test")
    _git(tmp_path, "config", "user.name", "One")
    _commit(tmp_path, "main.txt", "main\n", "main")
    _git(tmp_path, "merge", "--no-ff", "-q", "side", "-m", "merge side")

    result = activity_adapter(_context(tmp_path))

    assert result.diagnostics["pydriller"]["merge_commit_count"] == 1
    assert _metric(result, "pydriller:unique_authors").value == 2


def test_activity_adapter_surfaces_shallow_history_as_warning(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _init(source)
    _commit(source, "module.py", "one\n", "one")
    _commit(source, "module.py", "two\n", "two")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-local", str(source), str(shallow)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = activity_adapter(_context(shallow))

    assert result.status is AnalyzerStatus.WARN
    assert result.diagnostics["pydriller_status"] == "MEASURED"
    assert result.diagnostics["pydriller"]["history_is_shallow"] is True
    assert result.score is not None
