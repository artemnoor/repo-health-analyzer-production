"""Single-process analyzer worker entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from .analyzers import CANONICAL_ANALYZER_IDS, canonical_registry, register_default_factories
from .execution import LocalExecutor, WorkerExecutor
from .persistence import SQLitePersistence


def check() -> dict[str, object]:
    register_default_factories()
    canonical_registry.validate()
    return {"service": "repo-health-worker", "status": "ready", "analyzers": list(CANONICAL_ANALYZER_IDS)}


async def run_once() -> bool:
    # The queue lifecycle is intentionally explicit; deployments can inject a
    # configured CollectionService and factories instead of importing the API.
    store = SQLitePersistence(os.environ.get("REPO_HEALTH_DB", "repo-health.sqlite3"))
    try:
        register_default_factories()
        factories = {analyzer_id: canonical_registry.get(analyzer_id)[1] for analyzer_id in CANONICAL_ANALYZER_IDS}  # type: ignore[index]
        executor = LocalExecutor(factories)
        worker = WorkerExecutor(
            persistence=store, local=executor, worker_id=os.environ.get("REPO_HEALTH_WORKER_ID", "worker-1")
        )
        return await worker.run_once() is not None
    finally:
        store.close()


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
