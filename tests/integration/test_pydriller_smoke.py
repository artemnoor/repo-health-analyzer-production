"""Smoke coverage for the pinned PyDriller integration dependency."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydriller import Repository


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)


def test_pydriller_reads_commits_and_modifications(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "PyDriller Smoke Test")

    file_path = tmp_path / "module.py"
    file_path.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "module.py")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    file_path.write_text("value = 2\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "update")

    commits = list(Repository(str(tmp_path)).traverse_commits())

    assert [commit.msg for commit in commits] == ["initial", "update"]
    assert commits[1].author.name == "PyDriller Smoke Test"
    assert [(mod.new_path, mod.added_lines, mod.deleted_lines) for mod in commits[1].modified_files] == [
        ("module.py", 1, 1)
    ]
