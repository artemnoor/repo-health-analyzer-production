"""Verify the canonical production composition and optionally run a live smoke."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

from repo_health.analyzers import CANONICAL_ANALYZER_IDS
from repo_health.config import RuntimeConfig
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.persistence import SQLitePersistence
from repo_health.runtime import build_production_runtime

structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

_SOURCES = {
    "repo-health.documentation": ("Vale", "repo_health.collection.documentation.vale.ValeCollector"),
    "repo-health.activity": ("PyDriller/Git", "repo_health.collection.git.pydriller.PyDrillerCollector"),
    "repo-health.issues": ("SourceCraft Issues", "repo_health.collection.sourcecraft.SourceCraftIssuesCollector"),
    "repo-health.cicd": ("SourceCraft CI/CD", "repo_health.collection.sourcecraft.SourceCraftCicdCollector"),
    "repo-health.security": ("SourceCraft AppSec", "repo_health.collection.sourcecraft.SourceCraftAppSecCollector"),
    "repo-health.code-health": (
        "SonarQube/git-sizer/Git/TODO-history",
        "repo_health.collection.code_health production adapters",
    ),
}

_CAPABILITIES = {
    "repo-health.documentation": ("vale",),
    "repo-health.activity": ("git", "pydriller"),
    "repo-health.issues": ("sourcecraft",),
    "repo-health.cicd": ("sourcecraft",),
    "repo-health.security": ("sourcecraft",),
    "repo-health.code-health": ("git.todo-history", "git-sizer", "sonarqube"),
}


def _offline_rows(runtime) -> list[dict[str, object]]:
    capabilities = runtime.public_capabilities()
    rows = []
    for analyzer_id in CANONICAL_ANALYZER_IDS:
        source, adapter = _SOURCES[analyzer_id]
        relevant = _CAPABILITIES[analyzer_id]
        states = [capabilities[item]["state"] for item in relevant]
        status = "ready" if all(state == "available" for state in states) else "unavailable"
        rows.append(
            {
                "category": analyzer_id.removeprefix("repo-health."),
                "source": source,
                "adapter": adapter,
                "status": status,
                "score": None,
                "coverage": "unavailable",
                "confidence": "unknown",
                "evidence_count": 0,
                "live_verified": False,
            }
        )
    return rows


async def _live_rows(runtime, *, checkout_path: Path, repository: RepositoryRef) -> list[dict[str, object]]:
    request = AnalysisRequest(
        repository=repository,
        as_of=datetime.now(UTC),
        config_digest=runtime.config.digest(),
    )
    envelope = await runtime.orchestrator.analyze(request, checkout_path=checkout_path)
    by_id = {item.analyzer_id: item for item in envelope.category_results}
    rows = []
    for analyzer_id in CANONICAL_ANALYZER_IDS:
        result = by_id[analyzer_id]
        source, adapter = _SOURCES[analyzer_id]
        live_verified = all(
            runtime.public_capabilities()[capability]["state"] == "available"
            for capability in _CAPABILITIES[analyzer_id]
        )
        rows.append(
            {
                "category": result.category.value,
                "source": source,
                "adapter": adapter,
                "status": result.status.value,
                "score": result.score,
                "coverage": result.coverage.status,
                "confidence": result.confidence.level,
                "evidence_count": len(result.evidence),
                "live_verified": live_verified,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="run the real configured collection pipeline")
    parser.add_argument("--checkout-path", type=Path, default=None)
    parser.add_argument("--repository-id", default="team/production-fixture")
    parser.add_argument("--canonical-uri", default="https://sourcecraft.example/team/production-fixture")
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args(argv)

    config = RuntimeConfig.from_environment()
    runtime = build_production_runtime(config, mode="api", persistence=SQLitePersistence(":memory:"))
    try:
        payload: dict[str, object] = {
            "mode": "live" if args.live else "offline",
            "capabilities": runtime.public_capabilities(),
            "collector_source_ids": runtime.collector_source_ids,
        }
        if args.live:
            repository = RepositoryRef(
                repository_id=args.repository_id,
                canonical_uri=args.canonical_uri,
                provider="sourcecraft",
                ref=args.ref,
            )
            rows = asyncio.run(
                _live_rows(
                    runtime,
                    checkout_path=(args.checkout_path or Path(config.checkout_root)).resolve(),
                    repository=repository,
                )
            )
        else:
            rows = _offline_rows(runtime)
        payload["categories"] = rows
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
