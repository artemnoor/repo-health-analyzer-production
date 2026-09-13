"""Smoke-check paths, commands and pinned commits used by health docs."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("health.docs")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    required_paths = (
        "vendor/SOURCES.lock",
        "config/analyzers/native-tools.yaml",
        "config/analyzers/forge.yaml",
        "scripts/vendor_sources.py",
        "scripts/verify_source_update.py",
        "scripts/verify_health_stack.py",
        "packages/core/src/repowise/core/analysis/health/integrations/contracts.py",
        "packages/server/src/repowise/server/routers/code_health/canonical.py",
        "packages/server/src/repowise/server/routers/public_health.py",
        "packages/web/src/components/code-health/canonical-summary.tsx",
        "packages/web/src/app/ranking/page.tsx",
        "packages/ui/src/health/trend-chart.tsx",
        "packages/cli/src/repowise/cli/commands/health_cmd/summary.py",
        "packages/types/src/health-ranking.ts",
        "scripts/verify_health_completion.py",
        "docs/architecture/repository-health.md",
        "docs/reference/HEALTH_ANALYZER.md",
        "docs/reference/NATIVE_TOOLS.md",
        ".github/workflows/repository-health.yml",
    )
    missing = [path for path in required_paths if not (ROOT / path).exists()]
    if missing:
        raise RuntimeError(f"missing documented path(s): {', '.join(missing)}")

    ledger = json.loads((ROOT / "vendor/SOURCES.lock").read_text(encoding="utf-8"))
    native_doc = (ROOT / "docs/reference/NATIVE_TOOLS.md").read_text(encoding="utf-8")
    health_doc = (ROOT / "docs/reference/HEALTH_ANALYZER.md").read_text(encoding="utf-8")
    architecture_doc = (ROOT / "docs/architecture/repository-health.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    native_sources = {
        "scorecard",
        "repohealth",
        "criticality_score",
        "qlty",
        "sokrates",
        "sonarqube",
    }
    for entry in ledger["sources"]:
        commit = entry.get("commit")
        target = entry.get("target_root")
        if target and target != "." and not (ROOT / target).exists():
            raise RuntimeError(f"ledger target missing: {target}")
        if commit and entry["name"] in native_sources and commit not in native_doc:
            raise RuntimeError(f"native source commit not documented: {entry['name']} {commit}")

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/repository-health.yml").read_text(encoding="utf-8")
    )
    jobs = workflow.get("jobs", {}) if isinstance(workflow, dict) else {}
    expected_jobs = {"source-ledger", "python", "go", "rust", "java", "web", "composition"}
    if not expected_jobs.issubset(jobs):
        raise RuntimeError(f"workflow jobs missing: {sorted(expected_jobs - set(jobs))}")

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    commands = {
        "vendor-verify",
        "build-native",
        "test-python",
        "test-native",
        "test-composition",
        "health-sample",
        "health-replay",
        "health-clean",
        "health-completion",
        "health-contract",
    }
    missing_commands = sorted(command for command in commands if f"{command}:" not in makefile)
    if missing_commands:
        raise RuntimeError(f"Makefile commands missing: {', '.join(missing_commands)}")
    markers = (
        (health_doc, "score_projection.overall_score", "canonical projection field"),
        (health_doc, "0..100", "canonical score scale"),
        (health_doc, "Excellent | `90..100`", "ranking band boundary"),
        (health_doc, "`0` is a measured score", "zero/null semantics"),
        (health_doc, "include_ineligible=true", "public diagnostic filter"),
        (health_doc, "migration head `0066`", "migration compatibility note"),
        (health_doc, "### Release checkpoint", "release checkpoint"),
        (health_doc, "Windows without GNU Make", "Windows command fallback"),
        (architecture_doc, "derived band + facets", "derived ranking fields"),
        (architecture_doc, "no schema migration is introduced", "no-migration contract"),
        (architecture_doc, "make health-replay", "recovery command"),
        (readme, "docs/reference/HEALTH_ANALYZER.md", "README health reference"),
        (readme, "make health-contract", "README focused verification"),
        (readme, "legacy `0–10` scale", "README scale boundary"),
        (
            (ROOT / ".github/workflows/repository-health.yml").read_text(encoding="utf-8"),
            "artifacts/health-stack.log",
            "full gate artifact",
        ),
    )
    missing_markers = [label for text, marker, label in markers if marker not in text]
    if missing_markers:
        raise RuntimeError(f"documented contract markers missing: {', '.join(missing_markers)}")
    LOG.info(
        "documentation checkpoint passed paths=%d jobs=%d commands=%d markers=%d",
        len(required_paths),
        len(jobs),
        len(commands),
        len(markers),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOG.error("documentation checkpoint failed class=%s message=%s", type(exc).__name__, exc)
        raise SystemExit(1) from exc
