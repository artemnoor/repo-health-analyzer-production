from __future__ import annotations

import subprocess
from pathlib import Path

PINNED_REPOWISE_SHA = "1599224a3e4590c5d15a3d8e53727b9e74116ab9"


def test_pinned_repowise_tree_and_workspace_context_are_present() -> None:
    root = Path(__file__).resolve().parents[2]

    required_paths = (
        "pyproject.toml",
        "packages/core/src/repowise/core/analysis/health/engine.py",
        "packages/core/src/repowise/core/ingestion/git_indexer/indexer.py",
        "packages/cli/src/repowise/cli/main.py",
        ".ai-factory/config.yaml",
    )

    missing = [path for path in required_paths if not (root / path).exists()]
    assert not missing, f"RepoWise snapshot is incomplete: {missing}"

    checkout = root / ".sources" / "repowise"
    resolved_sha = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    assert resolved_sha == PINNED_REPOWISE_SHA
