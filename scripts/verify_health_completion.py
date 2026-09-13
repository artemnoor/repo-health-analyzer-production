#!/usr/bin/env python3
"""Verify that the Repository Health feature is complete at the source level.

The default mode is a fast, redacted contract check suitable for a local
release gate. ``--run-tests`` additionally runs the focused Python test set;
the web test/type-check commands remain separate because they require the
Node workspace runtime.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("health.completion")

REQUIRED_PATHS = (
    "config/analyzers/health-score.yaml",
    "config/analyzers/native-tools.yaml",
    "packages/core/alembic/versions/0065_health_score_projection.py",
    "packages/core/alembic/versions/0066_repository_health_ranking.py",
    "packages/core/src/repowise/core/analysis/health/composite.py",
    "packages/core/src/repowise/core/analysis/health/ranking_projection.py",
    "packages/core/src/repowise/core/analysis/health/integrations/orchestrator.py",
    "packages/core/src/repowise/core/persistence/crud/analysis/health_ranking.py",
    "packages/server/src/repowise/server/routers/code_health/canonical.py",
    "packages/server/src/repowise/server/routers/public_health.py",
    "packages/web/src/app/ranking/page.tsx",
    "packages/web/src/components/code-health/canonical-summary.tsx",
    "packages/web/src/components/code-health/canonical-summary.test.tsx",
    "packages/web/src/components/health-ranking/filters.tsx",
    "packages/web/src/components/health-ranking/ranking-page.tsx",
    "packages/web/src/components/health-ranking/compare-drawer.tsx",
    "packages/web/src/components/health-ranking/trend-chart.tsx",
    "packages/ui/src/health/ranking-tokens.ts",
    "packages/ui/src/health/trend-chart.tsx",
    "packages/web/playwright.config.ts",
    "packages/api-client/src/health-ranking.ts",
    "packages/types/src/health-ranking.ts",
    "packages/cli/src/repowise/cli/commands/health_cmd/summary.py",
    "tests/fixtures/health/calibration-matrix.json",
    "tests/unit/health/test_score_invariants.py",
    "tests/unit/health/test_ranking_contract.py",
    "tests/unit/persistence/test_health_ranking_projection.py",
    "tests/unit/server/test_health_canonical_score.py",
    "tests/unit/server/test_public_health_compare.py",
    "tests/unit/server/mcp/test_health_canonical_projection.py",
    "tests/unit/cli/test_health_canonical_contract.py",
    "tests/integration/test_health_completion_matrix.py",
    "tests/integration/test_health_batch_scale.py",
    "tests/e2e/health-ranking.spec.ts",
    "docs/architecture/repository-health.md",
    "docs/reference/HEALTH_ANALYZER.md",
    "docs/reference/NATIVE_TOOLS.md",
)

FOCUSED_TESTS = (
    "tests/unit/health/test_score_invariants.py",
    "tests/unit/persistence/test_health_ranking_projection.py",
    "tests/integration/test_health_completion_matrix.py",
    "tests/integration/test_health_batch_scale.py",
    "tests/unit/server/test_health_ranking.py",
    "tests/unit/server/test_public_health_compare.py",
    "tests/unit/server/test_health_canonical_score.py",
    "tests/unit/server/mcp/test_health_canonical_projection.py",
    "tests/unit/health/test_ranking_contract.py",
    "tests/unit/cli/test_health_canonical_contract.py",
    "tests/integration/test_public_health_ranking.py",
    "tests/integration/test_health_replay_rescore.py",
)


def _check_paths() -> None:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    if missing:
        raise RuntimeError(f"completion paths missing: {', '.join(missing)}")
    LOG.info("source contracts passed paths=%d", len(REQUIRED_PATHS))


def _check_fixture() -> None:
    payload = json.loads(
        (ROOT / "tests/fixtures/health/calibration-matrix.json").read_text(encoding="utf-8")
    )
    cases = payload.get("cases", [])
    required_kinds = {
        "healthy", "unhealthy", "partial", "stale", "no_git", "missing_tool",
        "tiny", "large", "monorepo", "multi_language",
    }
    actual_kinds = {case.get("kind") for case in cases if isinstance(case, dict)}
    if not required_kinds.issubset(actual_kinds):
        raise RuntimeError(f"calibration matrix missing cases: {sorted(required_kinds - actual_kinds)}")
    LOG.info("calibration fixture passed cases=%d", len(cases))


def _check_contract_markers() -> None:
    canonical_route = (
        ROOT / "packages/server/src/repowise/server/routers/code_health/canonical.py"
    ).read_text(encoding="utf-8")
    route = (ROOT / "packages/server/src/repowise/server/routers/public_health.py").read_text(
        encoding="utf-8"
    )
    page = (ROOT / "packages/web/src/app/ranking/page.tsx").read_text(encoding="utf-8")
    detail = (ROOT / "packages/web/src/components/code-health/canonical-summary.tsx").read_text(
        encoding="utf-8"
    )
    ranking_page = (ROOT / "packages/web/src/components/health-ranking/ranking-page.tsx").read_text(
        encoding="utf-8"
    )
    ranking_trend = (ROOT / "packages/web/src/components/health-ranking/trend-chart.tsx").read_text(
        encoding="utf-8"
    )
    shared_trend = (ROOT / "packages/ui/src/health/trend-chart.tsx").read_text(encoding="utf-8")
    cli_summary = (ROOT / "packages/cli/src/repowise/cli/commands/health_cmd/summary.py").read_text(
        encoding="utf-8"
    )
    migration = (ROOT / "packages/core/alembic/versions/0066_repository_health_ranking.py").read_text(
        encoding="utf-8"
    )
    markers = (
        (canonical_route, "score_projection", "canonical API projection"),
        (route, '@router.get("/compare"', "public compare route"),
        (route, '@router.get("/trend"', "public trend route"),
        (page, "RankingPage", "ranking page"),
        (ranking_page, "facets", "server-provided ranking facets"),
        (ranking_trend, "scoreScale={100}", "canonical trend scale"),
        (shared_trend, "scoreScale?: 10 | 100", "dual trend scale contract"),
        (detail, "score_projection", "canonical detail projection"),
        (detail, "Canonical repository score", "canonical detail headline"),
        (cli_summary, "canonical_score_label", "canonical CLI score"),
        (migration, "repository_health_ranking", "ranking migration"),
        (migration, '"visibility"', "visibility migration"),
    )
    missing = [label for text, marker, label in markers if marker not in text]
    if missing:
        raise RuntimeError(f"completion markers missing: {', '.join(missing)}")
    forbidden = (
        ("snapshot.score" in detail, "canonical detail legacy score fallback"),
        (re.search(r"/10(?!0)", detail) is not None, "canonical detail legacy scale"),
    )
    regressions = [label for found, label in forbidden if found]
    if regressions:
        raise RuntimeError(f"canonical contract regressions found: {', '.join(regressions)}")
    LOG.info("runtime/ranking contracts passed markers=%d forbidden=%d", len(markers), len(forbidden))


def _run_focused_tests() -> None:
    command = [sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS]
    LOG.info("running focused health tests count=%d", len(FOCUSED_TESTS))
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        raise RuntimeError(f"focused health tests failed exit={completed.returncode}")
    LOG.info("focused health tests passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    try:
        _check_paths()
        _check_fixture()
        _check_contract_markers()
        if args.run_tests:
            _run_focused_tests()
    except Exception as exc:
        LOG.error("completion check failed class=%s message=%s", type(exc).__name__, exc)
        return 1
    LOG.info("completion check passed run_tests=%s", args.run_tests)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
