"""Report optional external tool availability without making them runtime imports."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from repo_health.config import RuntimeConfig

TOOLS = ("git", "vale", "git-sizer")


def _tool_status(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def collect_report(root: Path) -> dict[str, object]:
    config = RuntimeConfig.from_environment()
    capabilities = {item.engine: item.public_dict() for item in config.capability_report()}
    return {
        "root": str(root),
        "tools": {name: _tool_status(name) for name in TOOLS},
        "capabilities": capabilities,
        "sonarqube_url_configured": config.sonar_url is not None,
        "sourcecraft_url_configured": config.sourcecraft_url is not None,
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
