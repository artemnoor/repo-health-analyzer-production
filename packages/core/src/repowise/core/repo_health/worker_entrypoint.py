"""Minimal worker process entry point for task validation/readiness checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .execution.tasks import AnalyzerTask
from .worker_runtime import WorkerConfig, readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repo Health worker boundary")
    parser.add_argument("--check", action="store_true", help="print redacted readiness configuration")
    parser.add_argument("--validate-task", type=Path, help="validate one serialized AnalyzerTask")
    args = parser.parse_args(argv)
    config = WorkerConfig.from_env()
    if args.validate_task is not None:
        task = AnalyzerTask.model_validate_json(args.validate_task.read_text(encoding="utf-8"))
        print(json.dumps({"valid": True, "task_id": task.task_id, "analyzer_id": task.analyzer_id}, sort_keys=True))
        return 0
    if args.check:
        print(
            json.dumps(
                {"config": config.redacted(), "readiness": readiness(config, database_available=bool(config.database_url), queue_available=True).model_dump()},
                sort_keys=True,
            )
        )
        return 0
    parser.error("one of --check or --validate-task is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
