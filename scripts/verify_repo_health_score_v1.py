"""Redacted live verification for the production Repo Health Score v1 path."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "artem03102006/codex-external-audit-public-20260916"
FIXTURE = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"


def _load_calibration() -> Any:
    path = ROOT / "spikes" / "scoring" / "calibration" / "run_calibration.py"
    spec = importlib.util.spec_from_file_location("repo_health_live_calibration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("calibration helper cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _category(result: Any) -> dict[str, Any]:
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    nested = {}
    for key in ("vale", "pydriller", "issues", "cicd", "appsec", "code_health"):
        if isinstance(diagnostics.get(key), dict):
            nested.update(diagnostics[key])
    coverage = diagnostics.get("coverage", nested.get("coverage"))
    confidence = diagnostics.get("confidence", nested.get("confidence"))
    if coverage is None or confidence is None:
        issues = diagnostics.get("issues")
        summary = issues.get("source_summary") if isinstance(issues, dict) else None
        if isinstance(summary, dict):
            coverage = summary.get("coverage", coverage)
            confidence = summary.get("confidence", confidence)
    return {
        "analyzer_id": result.analyzer_id,
        "status": result.status.value,
        "score": result.score,
        "coverage": coverage,
        "confidence": confidence,
        "finding_count": len(result.findings),
        "limitation_count": len(result.limitations),
        "findings": [
            {
                "subject": finding.subject,
                "severity": finding.severity,
                "location": finding.location.model_dump(mode="json") if finding.location else None,
                "evidence": [ref.json_pointer for ref in finding.evidence_refs],
            }
            for finding in result.findings
        ],
        "metrics": {
            metric.name: metric.value
            for metric in result.metrics
            if metric.name in {
                "vale:files_analyzed",
                "vale:weighted_findings",
                "pydriller:unique_commits",
                "pydriller:churn",
                "issues:open_issues",
                "issues:sample_size",
                "cicd:total_runs",
                "cicd:success_rate",
                "cicd:failure_rate",
                "appsec:active_findings",
                "code_health:maintainability_rating",
            }
        },
            "diagnostics": {
                key: diagnostics[key]
                for key in (
                    "issues_status",
                    "cicd_status",
                    "security_status",
                    "pydriller_status",
                    "active_severity_counts",
                    "applied_share",
                    "code_health",
                    "code_health_components",
                    "code_health_raw_score",
                    "code_health_eligible_weight",
                    "code_health_total_weight",
                    "code_health_score_before",
                    "code_health_score_after",
                )
                if key in diagnostics
            },
    }


def main() -> int:
    if not FIXTURE.is_dir():
        raise RuntimeError(f"fixture checkout is missing: {FIXTURE}")
    cal = _load_calibration()
    sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

    from repowise.core.analysis.health.integrations.appsec_analyzer import AppSecAnalyzer
    from repowise.core.analysis.health.integrations.chaoss_adapter import (
        activity_adapter,
        issues_prs_adapter,
    )
    from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer
    from repowise.core.analysis.health.integrations.code_health_analyzer import CodeHealthAnalyzer
    from repowise.core.analysis.health.integrations.code_health_collector import (
        CodeHealthFactsCollector,
    )
    from repowise.core.analysis.health.integrations.vale_adapter import vale_adapter
    from repowise.core.analysis.health.score_engine_v1 import compose_repo_health_score_v1

    with cal.api_client() as client:
        metadata = cal.sourcecraft_metadata(client, REPOSITORY)
        issues_inventory, issues_collection = cal.collect_issues(client, REPOSITORY)
        ci_inventory, ci_collection = cal.collect_ci(client, REPOSITORY)

    local_context = cal.context_for(REPOSITORY, FIXTURE, metadata)
    issues_context = cal.context_for(REPOSITORY, FIXTURE, metadata, issues_inventory)
    ci_context = cal.context_for(REPOSITORY, FIXTURE, metadata, {"sourcecraft_cicd": ci_inventory})
    appsec_context = cal.context_for(
        REPOSITORY,
        FIXTURE,
        metadata,
        {"repository_id": metadata.get("id")},
    )
    docs = vale_adapter(local_context)
    activity = activity_adapter(local_context)
    issues = issues_prs_adapter(issues_context)
    cicd = CICDAnalyzer().run(ci_context)
    security = AppSecAnalyzer().run(appsec_context)
    code_facts = CodeHealthFactsCollector().collect(local_context, baseline=None)
    code = CodeHealthAnalyzer().analyze(local_context, code_facts, None)
    results = (docs, activity, issues, cicd, security, code)
    score = compose_repo_health_score_v1(results)

    output = {
        "repository": REPOSITORY,
        "sourcecraft_metadata": {
            "status": metadata.get("status"),
            "repository_id_present": bool(metadata.get("id")),
            "default_branch": metadata.get("default_branch"),
        },
        "collections": {
            "issues": {key: issues_collection.get(key) for key in ("status", "records_received", "records_after_local_filter", "pages")},
            "cicd": {key: ci_collection.get(key) for key in ("status", "records_received", "records_after_local_filter", "pages")},
        },
        "categories": {name: _category(result) for name, result in zip(("Documentation", "Activity", "Issues", "CI/CD", "Security", "Code Health"), results, strict=True)},
        "score": {
            "version": score.version,
            "presentation_state": score.presentation_state,
            "overall": score.overall,
            "score_before_cap": score.score_before_cap,
            "coverage_k": score.coverage_k,
            "numeric_category_count": score.numeric_category_count,
            "category_scores": score.category_scores,
            "category_statuses": score.category_statuses,
            "category_quality": score.category_quality,
            "applied_caps": score.applied_caps,
            "excluded_categories": score.excluded_categories,
        },
        "token_logged": False,
        "raw_payloads_written": False,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
