"""Single-process analyzer worker entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json

from .analyzers import CANONICAL_ANALYZER_IDS
from .runtime import build_production_runtime


def check() -> dict[str, object]:
    runtime = build_production_runtime(mode="worker")
    try:
        return {
            "service": "repo-health-worker",
            "status": "ready",
            "analyzers": list(CANONICAL_ANALYZER_IDS),
            "collector_source_ids": list(runtime.collector_source_ids),
            "capabilities": runtime.public_capabilities(),
        }
    finally:
        runtime.close()


async def run_once() -> bool:
    runtime = build_production_runtime(mode="worker")
    try:
        return await runtime.worker_executor.run_once() is not None
    finally:
        runtime.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        print(json.dumps(check(), sort_keys=True))
        return 0
    if args.once:
        return 0 if asyncio.run(run_once()) else 2
    parser.error("one of --check or --once is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["check", "main", "run_once"]
