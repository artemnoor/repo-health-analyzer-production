"""Build the copied native health tools with explicit platform skips.

The Go tools are required for the local composition gate. Qlty and Sokrates
are built by their own CI jobs because their toolchains are platform-specific;
this command reports an unavailable optional toolchain as ``skipped`` instead
of pretending that an analyzer passed.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("health.build")

GO_TOOLS = (
    ("scorecard.local", ROOT / "vendor" / "scorecard", "./", "scorecard"),
    ("repohealth.baseline", ROOT / "vendor" / "repohealth", "./cmd/repohealth", "repohealth"),
    (
        "criticality.importance",
        ROOT / "vendor" / "criticality_score",
        "./cmd/scorer",
        "criticality-score",
    ),
)


def _run(label: str, command: list[str], cwd: Path) -> None:
    LOG.debug("build command=%s cwd=%s", command, cwd)
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    LOG.info("built tool=%s", label)


def _build_go() -> None:
    go = shutil.which("go")
    if go is None:
        raise RuntimeError("required toolchain go is unavailable")
    output_dir = ROOT / "bin"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    for label, cwd, package, name in GO_TOOLS:
        output = output_dir / f"{name}{suffix}"
        _run(
            label,
            [go, "build", "-buildvcs=false", "-o", str(output), package],
            cwd,
        )


def _optional_toolchains() -> None:
    if shutil.which("cargo") is None:
        LOG.warning("tool=qlty status=skipped reason=cargo-unavailable")
    else:
        LOG.info("tool=qlty status=skipped reason=run-cargo-in-dedicated-native-job")
    if shutil.which("mvn") is None:
        LOG.warning("tool=sokrates status=skipped reason=maven-unavailable")
    else:
        LOG.info("tool=sokrates status=skipped reason=run-maven-in-dedicated-native-job")


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s [%(name)s] %(message)s")
    LOG.debug("build-native root=%s", ROOT)
    _build_go()
    _optional_toolchains()
    LOG.info("native build passed required=3 optional=2")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOG.error("native build failed class=%s message=%s", type(exc).__name__, exc)
        raise SystemExit(1) from exc
