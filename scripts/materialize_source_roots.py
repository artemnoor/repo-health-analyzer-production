#!/usr/bin/env python3
"""Materialize lightweight Git metadata roots required by the source ledger.

The published repository keeps copied analyzer trees in ``vendor/`` but ignores
the local ``.sources/`` clones used to prove their pinned commits. CI creates
bare, blob-filtered repositories for those roots; the verifier needs commit and
tree objects, not a second checkout of every upstream source file.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "vendor" / "SOURCES.lock"
LOGGER = logging.getLogger("vendor.materialize")


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    LOGGER.debug("running command=%s cwd=%s", command, cwd)
    completed = subprocess.run(command, cwd=cwd, check=False, text=True, capture_output=True)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}: {detail}")


def _git_root_head(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode:
        return None
    return completed.stdout.strip()


def _entries() -> list[dict[str, Any]]:
    try:
        payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load {LEDGER_PATH}: {exc}") from exc
    entries = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError("source ledger must contain a sources array")
    return [entry for entry in entries if isinstance(entry, dict)]


def _materialize(entry: dict[str, Any]) -> None:
    if entry.get("copy_mode") == "reference-only":
        return
    name = str(entry.get("name", "<unnamed>"))
    relative = entry.get("source_root")
    url = entry.get("url")
    commit = entry.get("commit")
    if not isinstance(relative, str) or not isinstance(url, str) or not isinstance(commit, str):
        raise RuntimeError(f"{name}: ledger entry is missing source_root, url or commit")

    destination = ROOT / relative
    existing_head = _git_root_head(destination) if destination.exists() else None
    if existing_head == commit:
        LOGGER.info("source root already matches name=%s commit=%s", name, commit)
        return
    if destination.exists():
        raise RuntimeError(
            f"{name}: source root exists but does not match {commit}; "
            "remove it explicitly before retrying"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{name}-", dir=str(destination.parent)) as temp:
        temporary = Path(temp) / "source.git"
        _run(["git", "init", "--bare", str(temporary)])
        _run(["git", "-C", str(temporary), "remote", "add", "origin", url])
        _run(
            [
                "git",
                "-C",
                str(temporary),
                "fetch",
                "--no-tags",
                "--filter=blob:none",
                "--depth=1",
                "origin",
                f"{commit}:refs/heads/pinned",
            ]
        )
        _run(["git", "-C", str(temporary), "symbolic-ref", "HEAD", "refs/heads/pinned"])
        if destination.exists():
            raise RuntimeError(f"{name}: source root appeared during materialization: {destination}")
        temporary.rename(destination)
    LOGGER.info("materialized source root name=%s commit=%s", name, commit)


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    for entry in _entries():
        _materialize(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
