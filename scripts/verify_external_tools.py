"""Report optional external tool availability without making them runtime imports."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

TOOLS = ("git", "vale", "git-sizer", "sonar-scanner")


def _tool_status(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def collect_report(root: Path) -> dict[str, object]:
    return {
        "root": str(root),
        "tools": {name: _tool_status(name) for name in TOOLS},
        "sonarqube_url_configured": bool(os.environ.get("SONARQUBE_URL")),
        "runtime_mode": "adapter/process-boundary",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to report (defaults to the current repository).",
    )
    args = parser.parse_args()
    print(json.dumps(collect_report(args.root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
