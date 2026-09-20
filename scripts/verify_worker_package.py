"""Verify the selected single-worker boundary and its artifact allowlist."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = ROOT / "packages" / "core" / "src" / "repowise" / "core" / "repo_health"


def main() -> int:
    required = (
        WORKER_ROOT / "worker_entrypoint.py",
        WORKER_ROOT / "worker_runtime.py",
        WORKER_ROOT / "execution" / "tasks.py",
        WORKER_ROOT / "execution" / "worker.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"worker boundary is incomplete: {missing}")
    forbidden_fragments = ("tests", "spikes", "vendor", "$out")
    for path in WORKER_ROOT.rglob("*"):
        if path.is_file() and any(fragment in path.parts for fragment in forbidden_fragments):
            raise SystemExit(f"forbidden worker artifact path: {path.relative_to(ROOT)}")
    environment = os.environ.copy()
    environment["REPO_HEALTH_QUEUE_BACKEND"] = "memory"
    environment.pop("REPO_HEALTH_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "repowise.core.repo_health.worker_entrypoint", "--check"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    if not payload["readiness"]["ready"] or payload["config"]["database_configured"]:
        raise SystemExit("worker readiness/configuration verification failed")
    if "REPO_HEALTH_DATABASE_URL" in result.stdout or "password" in result.stdout.casefold():
        raise SystemExit("worker verification leaked a secret-bearing field")
    print(json.dumps({"worker": "ready", "artifact": "allowlist-verified"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
