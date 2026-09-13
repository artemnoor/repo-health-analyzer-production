"""Run copied native tests with explicit, non-green platform skip reasons."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("health.native-tests")


def _run(label: str, cwd: Path, command: list[str]) -> None:
    LOG.debug("test command=%s cwd=%s", command, cwd)
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    LOG.info("passed tool=%s", label)


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s [%(name)s] %(message)s")
    if shutil.which("go") is None:
        raise RuntimeError("required toolchain go is unavailable")
    _run("repohealth", ROOT / "vendor" / "repohealth", ["go", "test", "./..."])
    _run("criticality_score", ROOT / "vendor" / "criticality_score", ["go", "test", "./..."])

    if sys.platform == "win32":
        LOG.warning(
            "skipped tool=scorecard reason=upstream suite requires POSIX paths/symlink privileges and GitHub credentials"
        )
    else:
        _run("scorecard", ROOT / "vendor" / "scorecard", ["go", "test", "./..."])

    if shutil.which("cargo") is None:
        LOG.warning("skipped tool=qlty reason=cargo-unavailable")
    elif sys.platform == "win32" and shutil.which("link") is None:
        LOG.warning("skipped tool=qlty reason=MSVC-linker-unavailable")
    else:
        _run("qlty", ROOT / "vendor" / "qlty", ["cargo", "test", "--workspace"])

    if shutil.which("mvn") is None:
        LOG.warning("skipped tool=sokrates reason=maven-unavailable")
    else:
        _run("sokrates", ROOT / "vendor" / "sokrates", ["mvn", "-pl", "cli", "-am", "test"])
    LOG.info("native test matrix completed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOG.error("native tests failed class=%s message=%s", type(exc).__name__, exc)
        raise SystemExit(1) from exc
