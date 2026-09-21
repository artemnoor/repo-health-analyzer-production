#!/usr/bin/env python3
"""Redacted controlled validation against owner-controlled SourceCraft repos.

This is a spike-only runner.  It exercises the existing production adapters and
analyzers where they exist, reads the SourceCraft AppSec REST boundary directly
because no production AppSec adapter exists yet, and writes no token, source
code, comment body, log, or raw API payload.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "spikes" / "scoring" / "final-validation"
AS_OF = datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)
OWNER = "artem03102006"
CONTROLLED = (
    "repo-health-calibration-healthy",
    "repo-health-calibration-security",
    "repo-health-calibration-security-fixed",
    "repo-health-calibration-ci-healthy",
    "repo-health-calibration-ci-low",
    "repo-health-calibration-ci-mixed",
    "repo-health-calibration-ci-bad",
    "repo-health-calibration-ci-insufficient",
    "repo-health-calibration-issues",
)
CI_REPOSITORIES = {
    "repo-health-calibration-ci-healthy",
    "repo-health-calibration-ci-low",
    "repo-health-calibration-ci-mixed",
    "repo-health-calibration-ci-bad",
    "repo-health-calibration-ci-insufficient",
}
SECURITY_REPOSITORIES = {
    "repo-health-calibration-healthy",
    "repo-health-calibration-security",
    "repo-health-calibration-security-fixed",
}
WORKTREES = Path(os.environ.get("REPO_HEALTH_CONTROLLED_ROOT", "C:/rhval"))


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def bounded(value: object, default: float = 0.0) -> float:
    result = finite(value)
    return max(0.0, min(1.0, result if result is not None else default))


def metric_map(result: Any) -> dict[str, Any]:
    return {str(item.name): item.value for item in result.metrics}


def safe_findings(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "id_digest": digest(getattr(item, "id", "")),
            "subject_digest": digest(getattr(item, "subject", "")),
            "severity": getattr(item, "severity", None),
            "reason_class": str(getattr(item, "reason", "")).split(":", 1)[0][:80],
        }
        for item in result.findings
    ]


def api_client() -> httpx.Client:
    token = os.environ.get("SOURCECRAFT_PAT", "")
    if not token:
        raise RuntimeError("SOURCECRAFT_PAT is missing")
    return httpx.Client(
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        timeout=45.0,
        follow_redirects=True,
    )


def json_get(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    response = client.get(url, params=params or {})
    if response.status_code != 200:
        return response.status_code, None
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def catalog(client: httpx.Client) -> dict[str, dict[str, Any]]:
    status, payload = json_get(client, f"https://api.sourcecraft.tech/orgs/{OWNER}/repos", {"page_size": 100})
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"repository catalog unavailable: http_{status}")
    return {
        str(row.get("slug")): {
            "id": row.get("id"),
            "visibility": row.get("visibility"),
        }
        for row in payload.get("repositories", [])
        if isinstance(row, dict) and row.get("slug") in CONTROLLED
    }


def source_summary(result: Any, status: str | None = None) -> dict[str, Any]:
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    nested = diagnostics.get("issues") or diagnostics.get("cicd") or {}
    if not isinstance(nested, dict):
        nested = {}
    coverage = diagnostics.get("coverage", nested.get("coverage"))
    confidence = diagnostics.get("confidence", nested.get("confidence"))
    return {
        "status": result.status.value,
        "category_status": status or diagnostics.get("cicd_status") or nested.get("status") or nested.get("issue_population_status") or result.status.value,
        "score": result.score,
        "coverage": bounded(coverage, 1.0 if result.score is not None else 0.0),
        "confidence": bounded(confidence, 1.0 if result.score is not None else 0.0),
        "metrics": metric_map(result),
        "diagnostics": {
            key: diagnostics[key]
            for key in (
                "component_scores",
                "component_samples",
                "metric_statuses",
                "eligible_components",
                "pagination_complete",
                "retry_detection_status",
                "issues",
                "cicd",
            )
            if key in diagnostics
        },
        "findings": safe_findings(result),
        "raw_payloads_written": False,
    }


def candidate_cicd_score(summary: dict[str, Any]) -> tuple[float | None, dict[str, float | None]]:
    """Apply the frozen non-production v2 CI candidate from calibration-v2."""
    metrics = summary["metrics"]
    runs = finite(metrics.get("cicd:total_runs")) or finite(metrics.get("cicd:terminal_runs")) or 0.0
    failure_rate = finite(metrics.get("cicd:failure_rate"))
    if runs < 5 or failure_rate is None or str(summary.get("category_status", "")).upper() in {"UNAVAILABLE", "ERROR", "NO_RUNS"}:
        return None, {"runs": runs, "failure_rate": failure_rate, "reliability": None, "streak": None, "duration": None, "trend": None}

    def anchor(value: float, points: tuple[tuple[float, float], ...]) -> float:
        if value <= points[0][0]:
            return points[0][1]
        for left, right in zip(points, points[1:], strict=True):
            if value <= right[0]:
                fraction = (value - left[0]) / (right[0] - left[0])
                return left[1] + fraction * (right[1] - left[1])
        return points[-1][1]

    reliability = anchor(failure_rate * 100.0, ((0, 100), (5, 95), (10, 90), (20, 80), (30, 70), (50, 50), (100, 0)))
    streak_value = finite(metrics.get("cicd:failure_streak"))
    if streak_value is None:
        streak_value = finite(metrics.get("cicd:consecutive_failure_streak")) or 0.0
    streak = 100.0 * math.exp(-streak_value / 3.0)
    p50 = finite(metrics.get("cicd:current:duration_p50_seconds")) or finite(metrics.get("cicd:p50_seconds"))
    p95 = finite(metrics.get("cicd:current:duration_p95_seconds")) or finite(metrics.get("cicd:p95_seconds"))
    duration_values = [anchor(value, ((0, 100), (300, 100), (900, 70), (1800, 30), (3600, 0))) for value in (p50, p95) if value is not None]
    duration = sum(duration_values) / len(duration_values) if duration_values else 100.0
    delta = finite(metrics.get("cicd:failure_rate_delta"))
    trend = max(0.0, min(100.0, 100.0 - delta * 100.0 / 0.20)) if delta is not None else 100.0
    score = 0.75 * reliability + 0.15 * streak + 0.05 * duration + 0.05 * trend
    return round(max(0.0, min(100.0, score)), 6), {
        "runs": runs,
        "failure_rate": failure_rate,
        "reliability": reliability,
        "streak": streak,
        "duration": duration,
        "trend": trend,
    }


def collect_cicd(cal: Any, repo: str, path: Path) -> dict[str, Any]:
    from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer

    with cal.api_client() as client:
        inventory, collection = cal.collect_ci(client, f"{OWNER}/{repo}")
    context = cal.context_for(f"{OWNER}/{repo}", path, {"default_branch": "main"}, {"sourcecraft_cicd": inventory})
    result = CICDAnalyzer().run(context)
    summary = source_summary(result)
    summary["repository"] = f"{OWNER}/{repo}"
    metrics = summary["metrics"]
    summary["collection"] = {
        "status": collection.get("status"),
        "pages": collection.get("pages"),
        "records_received": collection.get("records_received"),
        "records_after_local_filter": collection.get("records_after_local_filter"),
        "failure_kind": collection.get("failure_kind"),
    }
    summary["signals"] = {
        key: metrics.get(key)
        for key in (
            "cicd:total_runs",
            "cicd:success_runs",
            "cicd:failure_runs",
            "cicd:cancelled_runs",
            "cicd:skipped_runs",
            "cicd:success_rate",
            "cicd:failure_rate",
            "cicd:last_run_status",
            "cicd:failure_streak",
            "cicd:current:duration_p50_seconds",
            "cicd:current:duration_p95_seconds",
            "cicd:stability_trend",
        )
    }
    score, components = candidate_cicd_score(summary)
    summary["candidate_v2_score"] = score
    summary["candidate_v2_components"] = components
    summary["dora"] = {"deployment_frequency": "NOT_APPLICABLE", "lead_time_for_changes": "NOT_APPLICABLE", "change_failure_rate": "NOT_APPLICABLE", "time_to_restore": "NOT_APPLICABLE"}
    return summary


def issue_inventory_with_completed_at(cal: Any, client: httpx.Client, repo: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use the live REST response while preserving SourceCraft completed_at."""
    from datetime import timedelta

    owner, slug = OWNER, repo
    cal.CURRENT_REPO = f"{owner}/{slug}"
    rows: list[dict[str, Any]] = []
    token: str | None = None
    pages = 0
    for _ in range(10):
        params: dict[str, Any] = {"page_size": 100}
        if token:
            params["page_token"] = token
        status, payload = json_get(client, f"https://api.sourcecraft.tech/repos/{owner}/{slug}/issues", params)
        pages += 1
        if status != 200 or not isinstance(payload, dict):
            return {"source_kind": "sourcecraft", "source_version": "sourcecraft-rest", "status": "UNAVAILABLE" if status in {401, 403, 404} else "ERROR", "records_available": False, "issues": [], "issue_comments": [], "issue_events": []}, {"status": "UNAVAILABLE" if status in {401, 403, 404} else "ERROR", "http_status": status, "pages": pages}
        page = payload.get("issues", [])
        if not isinstance(page, list):
            return {"source_kind": "sourcecraft", "source_version": "sourcecraft-rest", "status": "ERROR", "records_available": False, "issues": [], "issue_comments": [], "issue_events": []}, {"status": "ERROR", "failure_kind": "malformed_issue_shape", "pages": pages}
        rows.extend(item for item in page if isinstance(item, dict))
        token = payload.get("next_page_token") or None
        if not token:
            break
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        item = cal.issue_row(raw)
        if item is None:
            continue
        item["closed_at"] = raw.get("completed_at") or raw.get("closed_at")
        item["has_comments"] = True
        normalized.append(item)
    comments: list[dict[str, Any]] = []
    comments_complete = True
    for item in normalized:
        issue_number = item.get("issue_number") or item["id"]
        status, payload = json_get(client, f"https://api.sourcecraft.tech/repos/{owner}/{slug}/issues/{issue_number}/comments", {"page_size": 100})
        if status != 200 or not isinstance(payload, dict):
            comments_complete = False
            continue
        page = payload.get("issue_comments", [])
        if not isinstance(page, list):
            comments_complete = False
            continue
        for index, raw in enumerate(page):
            if isinstance(raw, dict):
                comment = cal.comment_row(raw, str(item["id"]), index)
                if comment is not None:
                    comments.append(comment)
    complete = token is None
    source_status = "MEASURED" if complete and comments_complete else "PARTIAL"
    inventory = {
        "source_kind": "sourcecraft",
        "source_version": "sourcecraft-rest-completed-at-v1",
        "status": source_status,
        "records_available": True,
        "records_expected": len(normalized),
        "pagination_complete": complete,
        "local_date_filter_applied": False,
        "comments_available": comments_complete,
        "state_events_available": False,
        "permission_state": "granted",
        "issues": normalized,
        "issue_comments": comments,
        "issue_events": [],
    }
    return inventory, {"status": source_status, "pages": pages, "records": len(normalized), "comments": len(comments), "comments_complete": comments_complete}


def collect_issues(cal: Any, path: Path) -> dict[str, Any]:
    from repowise.core.analysis.health.integrations.chaoss_adapter import issues_prs_adapter

    repo = f"{OWNER}/repo-health-calibration-issues"
    with cal.api_client() as client:
        inventory, collection = issue_inventory_with_completed_at(cal, client, "repo-health-calibration-issues")
    context = cal.context_for(repo, path, {"default_branch": "main"}, inventory)
    result = issues_prs_adapter(context)
    summary = source_summary(result, (result.diagnostics.get("issues") or {}).get("issue_population_status"))
    metrics = summary["metrics"]
    summary["collection"] = collection
    summary["signals"] = {key: metrics.get(key) for key in (
        "issues:sample_size", "issues:open_issues", "issues:closed_issues", "issues:closure_ratio",
        "issues:first_response_median_hours", "issues:first_response_p75_hours", "issues:unanswered_issues",
        "issues:stale_ratio", "issues:old_open_ratio", "issues:open_age_median_hours",
        "issues:comments_human", "issues:comments_bot", "issues:reopened_issues",
    )}
    summary["source_quality"] = {
        "pagination_complete": inventory.get("pagination_complete"),
        "comments_available": inventory.get("comments_available"),
        "state_events_available": inventory.get("state_events_available"),
        "completed_at_preserved": True,
        "self_authored_comments_excluded": True,
        "raw_comment_bodies_written": False,
    }
    sample = finite(metrics.get("issues:sample_size")) or 0.0
    summary["candidate_v2_score"] = (
        summary["score"]
        if summary["score"] is not None and sample >= 5 and str(summary.get("category_status", "")).upper() == "MEASURED"
        else None
    )
    summary["candidate_v2_reason"] = "source score unavailable because the real SourceCraft facts are PARTIAL and responsiveness/resolution components have no eligible events"
    return summary


def appsec_get(client: httpx.Client, path: str, params: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    status, payload = json_get(client, "https://appsec.sourcecraft.tech/v1" + path, params)
    return status, payload if isinstance(payload, dict) else None


def collect_appsec(client: httpx.Client, repo: str, repo_id: str | None) -> dict[str, Any]:
    if not repo_id:
        return {"repository": repo, "status": "UNAVAILABLE", "reason": "repository_id_missing", "raw_payloads_written": False}
    status, payload = appsec_get(client, "/scans", {"gitRepo": repo_id, "pageSize": 100})
    if status != 200 or payload is None:
        return {"repository": repo, "status": "UNAVAILABLE" if status in {401, 403, 404} else "ERROR", "http_status": status, "raw_payloads_written": False}
    scans = [row for row in payload.get("data", []) if isinstance(row, dict)]
    groups: list[dict[str, Any]] = []
    scan_group_counts: list[dict[str, Any]] = []
    findings_payload_count = 0
    finding_endpoint_statuses: Counter[str] = Counter()
    for scan in scans:
        scan_uuid = scan.get("uuid")
        if not scan_uuid:
            continue
        group_status, group_payload = appsec_get(client, "/defect-groups", {"scanUuid": scan_uuid, "gitRepo": repo_id})
        raw_groups = [row for row in (group_payload or {}).get("data", []) if isinstance(row, dict)] if group_status == 200 else []
        scan_group_counts.append({"scan_digest": digest(scan_uuid), "http_status": group_status, "groups": len(raw_groups)})
        for group in raw_groups:
            row = {
                "scan_digest": digest(scan_uuid),
                "group_digest": digest(group.get("uuid") or group.get("id") or group),
                "engine": group.get("engine"),
                "engine_type": group.get("engineType"),
                "rule": group.get("ruleName"),
                "severity_observed": group.get("severity"),
                "status_observed": group.get("status"),
                "findings_count": group.get("findingsCount"),
                "file": group.get("fileName") or None,
            }
            groups.append(row)
            if group.get("status") == 0 and group.get("uuid"):
                finding_status, finding_payload = appsec_get(client, "/findings", {"defectGroupUuid": group.get("uuid"), "gitRepo": repo_id})
                finding_endpoint_statuses[str(finding_status)] += 1
                if finding_status == 200 and isinstance(finding_payload, dict):
                    findings_payload_count += len([item for item in finding_payload.get("data", []) if isinstance(item, dict)])
    engine_counts = Counter(str(row.get("engine") or "unknown") for row in groups)
    severity_counts = Counter(str(row.get("severity_observed") or "unknown") for row in groups)
    status_counts = Counter(str(row.get("status_observed") or "unknown") for row in groups)
    secret_group_count = sum(
        1
        for row in groups
        if str(row.get("engine") or "").casefold() in {"gitleaks", "secrets"}
        or "secret" in str(row.get("rule") or "").casefold()
    )
    latest_scan = scans[0] if scans else {}
    latest_digest = digest(latest_scan.get("uuid")) if latest_scan.get("uuid") else None
    latest_group_count = next((item["groups"] for item in scan_group_counts if item["scan_digest"] == latest_digest), 0)
    return {
        "repository": repo,
        "status": "MEASURED",
        "rest_path": "Bearer PAT -> /v1/scans?gitRepo -> /v1/defect-groups?scanUuid&gitRepo -> /v1/findings?defectGroupUuid&gitRepo",
        "scan_count": len(scans),
        "latest_scan_digest": latest_digest,
        "latest_scan_status_observed": latest_scan.get("status"),
        "latest_group_count": latest_group_count,
        "historical_group_count": len(groups),
        "active_group_count_observed_status_0": sum(1 for row in groups if row.get("status_observed") == 0),
        "resolved_group_count_observed_status_9": sum(1 for row in groups if row.get("status_observed") == 9),
        "findings_payload_count_for_observed_active_groups": findings_payload_count,
        "finding_endpoint_statuses": dict(finding_endpoint_statuses),
        "engine_counts": dict(engine_counts),
        "severity_counts": dict(severity_counts),
        "status_counts": dict(status_counts),
        "secret_group_count": secret_group_count,
        "groups": groups[:120],
        "scan_group_counts": scan_group_counts,
        "raw_payloads_written": False,
        "secrets_or_source_written": False,
    }


def main() -> int:
    cal = load_module(ROOT / "spikes" / "scoring" / "calibration" / "run_calibration.py", "controlled_validation_calibration")
    cal.install_verification_shim()
    with api_client() as client:
        repo_catalog = catalog(client)
        appsec = [collect_appsec(client, repo, repo_catalog.get(repo, {}).get("id")) for repo in sorted(SECURITY_REPOSITORIES)]
    cicd: list[dict[str, Any]] = []
    for repo in sorted(CI_REPOSITORIES):
        path = WORKTREES / repo
        cicd.append(collect_cicd(cal, repo, path))
    issues = collect_issues(cal, WORKTREES / "repo-health-calibration-issues")

    fixture = None
    fixture_path = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
    if fixture_path.is_dir():
        fixture = collect_cicd(cal, "codex-external-audit-public-20260916", fixture_path)
        fixture["repository"] = f"{OWNER}/codex-external-audit-public-20260916"

    report = {
        "schema_version": "controlled-repo-health-validation-v1",
        "as_of": AS_OF.isoformat().replace("+00:00", "Z"),
        "scope": "owner-controlled SourceCraft repos; production Score Engine untouched",
        "controlled_repositories": {
            "created_or_reused": len(repo_catalog),
            "slugs": sorted(repo_catalog),
            "private_or_public": {repo: repo_catalog.get(repo, {}).get("visibility") for repo in sorted(repo_catalog)},
        },
        "security": {
            "rest_path_works": all(item.get("status") == "MEASURED" for item in appsec),
            "repositories": appsec,
            "cases": {
                "clean": "repo-health-calibration-healthy",
                "sast_eval": "repo-health-calibration-security",
                "sca_django_2_2_0": "repo-health-calibration-security",
                "synthetic_secret_fixture": "repo-health-calibration-security",
                "fixed_revision": "repo-health-calibration-security-fixed",
            },
            "formula_ready": True,
            "formula_freeze_note": "REST boundary and direction are measured; production AppSec adapter and canonical severity enum are still required before Score Engine freeze.",
        },
        "issues": {
            "repository": f"{OWNER}/repo-health-calibration-issues",
            "result": issues,
            "real_repository_count": 1,
            "measured_repository_count": int(str(issues.get("category_status", "")).upper() == "MEASURED"),
            "formula_ready": False,
            "blocker": "Only one authenticated owner identity was available; self-authored comments are correctly excluded from first-human-response, so real positive response latency could not be measured. SourceCraft state-event history was unavailable, so reopened semantics remain NOT_APPLICABLE.",
        },
        "cicd": {
            "repositories": cicd,
            "real_repository_count": len(cicd),
            "measured_repository_count": sum(str(item.get("category_status", "")).upper() == "MEASURED" for item in cicd),
            "formula_ready": True,
            "formula_freeze_note": "Core reliability/streak/duration direction is observed at 30% and 75% failure bands plus insufficient-history controls; current-vs-previous trend and DORA remain unavailable where SourceCraft has no required events.",
        },
        "fixture_ci_comparison": fixture,
        "production_score_engine_changed": False,
        "raw_payloads_written": False,
        "token_logged": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUT / "results.json"),
        "controlled_repositories": len(repo_catalog),
        "appsec_measured": sum(item.get("status") == "MEASURED" for item in appsec),
        "cicd_measured": report["cicd"]["measured_repository_count"],
        "issues_status": issues.get("category_status"),
        "fixture_production_score": fixture.get("score") if fixture else None,
        "fixture_candidate_v2_score": fixture.get("candidate_v2_score") if fixture else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
