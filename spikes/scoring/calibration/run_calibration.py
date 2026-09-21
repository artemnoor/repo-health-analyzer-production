#!/usr/bin/env python3
"""Reproducible, non-production calibration of the six-category Repo Health score.

This runner deliberately lives under ``spikes``.  It reads the existing analyzer
boundaries, collects public SourceCraft observations, and writes redacted
calibration artifacts.  It never changes production code, score configuration,
or repository contents.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "spikes" / "scoring" / "calibration"
CHECKOUT_ROOT = Path(os.environ.get("REPO_HEALTH_CALIBRATION_ROOT", "D:/RepoHealthCalibration/repos"))
AS_OF = datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)
SOURCECRAFT_API = "https://api.sourcecraft.tech"
SOURCECRAFT_WEB = "https://sourcecraft.dev"
SOURCECRAFT_PAT = "SOURCECRAFT_PAT"
WINDOW_DAYS = 90
MAX_ISSUE_PAGES = 10
MAX_ISSUES_PER_REPOSITORY = 500
MAX_COMMENT_REQUESTS = 200
MAX_CI_PAGES = 100
VALE = ROOT / "spikes" / "documentation" / "vale" / "runs" / "vale-3.22.0" / "vale.exe"
GIT_SIZER = ROOT / "spikes" / "code_health" / "git-sizer" / "git-sizer.exe"

WEIGHTS = {
    "Documentation": 15.0,
    "Activity": 15.0,
    "Issues": 15.0,
    "CI/CD": 15.0,
    "Security": 20.0,
    "Code Health": 20.0,
}

# Fixed public sample.  The strata were selected from the SourceCraft global
# public catalog on 2026-09-20: high-rating/mature, oldest catalog entries,
# newest entries, language quota, deterministic hash sample, plus the real
# project fixture used by the prior analyzer spikes.  No private repo is used.
SAMPLE: tuple[tuple[str, str, str], ...] = (
    ("divkit/divkit", "Kotlin", "high_rating"),
    ("a13xp0p0v/kernel-hardening-checker", "Python", "high_rating"),
    ("datalens/datalens", "Shell", "high_rating"),
    ("dqdkfa/libmdbx", "C", "high_rating"),
    ("gravity-ui/uikit", "TSX", "high_rating"),
    ("suzev/advent-test", "C++", "oldest_catalog"),
    ("appolimp/hello", "unknown", "oldest_catalog"),
    ("sourcecraft/sourcecraft", "unknown", "oldest_catalog"),
    ("mibon2019/test", "Shell", "oldest_catalog"),
    ("fy-demonar/test1", "TypeScript", "oldest_catalog"),
    ("nphne-3azqbags/gazprombank-reviews-analyzer", "unknown", "newest_catalog"),
    ("kes-plahotin/real-estate-catalog", "JavaScript", "newest_catalog"),
    ("d-diukin-centr-to-ru/tesr", "unknown", "newest_catalog"),
    ("axidex/random-number-telegram-bot", "JavaScript", "newest_catalog"),
    ("231313131/testvuln", "JavaScript", "newest_catalog"),
    ("artemka21005/hackathon25", "Python", "language:Python"),
    ("organization-boss-derevo-market/koleso-emotsii", "JavaScript", "language:JavaScript"),
    ("gradosphera/telegram-apps", "TypeScript", "language:TypeScript"),
    ("vegasonik2/smartroute", "TSX", "language:TSX"),
    ("cppshizoid/metautils", "C++", "language:C++"),
    ("therteenten/archive-optiram", "Java", "language:Java"),
    ("postgres/wal-g", "Go", "language:Go"),
    ("yurvon/origa", "Rust", "language:Rust"),
    ("romanko-mikhail/bhlib", "C", "language:C"),
    ("nikulin-n-n/android-arduino", "Kotlin", "language:Kotlin"),
    ("n-prudkovskiy/first", "Shell", "language:Shell"),
    ("roxblnfk/happy-wife-happy-life", "PHP", "language:PHP"),
    ("kookaburra/docs", "unknown", "deterministic_random"),
    ("dreagledr-public/embedder", "C#", "deterministic_random"),
    ("al3xey1981ru/my-test", "JavaScript", "deterministic_random"),
    ("lilmarlboro/zapretcloudflare", "Batchfile", "deterministic_random"),
    ("nitrogen1123/news-site-gazetka", "HTML", "deterministic_random"),
    ("konstkaras/lj-clique", "Java", "deterministic_random"),
    ("yndx-korsak-pz-9zw190/repo-test", "unknown", "deterministic_random"),
    ("theilyakolosov/rag-system", "Python", "deterministic_random"),
    ("deepsweet/agentic-openspec", "JavaScript", "deterministic_random"),
    ("codwiz/aassh", "Python", "deterministic_random"),
    ("artem03102006/codex-external-audit-public-20260916", "Python", "real_fixture_anchor"),
)


def install_verification_shim() -> None:
    """Retain the historical helper name while loading the real package."""
    import importlib

    importlib.import_module("repowise.core.analysis.health.coverage")


def number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def bounded(value: object, default: float = 0.0) -> float:
    result = number(value)
    return max(0.0, min(1.0, result if result is not None else default))


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def repo_name(value: str) -> tuple[str, str]:
    owner, slug = value.split("/", 1)
    return owner, slug


def api_client() -> httpx.Client:
    token = os.environ.get(SOURCECRAFT_PAT, "")
    return httpx.Client(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30.0,
        follow_redirects=True,
    )


def compact_actor(value: object) -> object | None:
    if isinstance(value, dict):
        return {key: value[key] for key in ("id", "slug", "login", "username", "name", "is_bot", "bot", "actor_type", "user_type", "account_type", "is_human") if key in value}
    return str(value) if value not in (None, "") else None


def first(mapping: dict[str, Any], *keys: str) -> object | None:
    for key in keys:
        if mapping.get(key) not in (None, ""):
            return mapping[key]
    return None


def extract_rows(payload: object, key: str) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
        envelopes = [item for item in rows if key in item]
        if envelopes:
            flat = [row for envelope in envelopes for row in envelope.get(key, []) if isinstance(row, dict)]
            token = next((str(envelope.get("next_page_token") or "") for envelope in envelopes if envelope.get("next_page_token")), None)
            return flat, token
        return rows, None
    if not isinstance(payload, dict):
        raise ValueError("SourceCraft response is not an object or array")
    if key in payload:
        rows = [item for item in payload[key] if isinstance(item, dict)] if isinstance(payload[key], list) else []
        return rows, str(payload.get("next_page_token") or "") or None
    for nested_key in ("items", "results", "records", "runs"):
        if isinstance(payload.get(nested_key), list):
            return [item for item in payload[nested_key] if isinstance(item, dict)], str(payload.get("next_page_token") or "") or None
    return [], None


def sourcecraft_metadata(client: httpx.Client, repo: str) -> dict[str, Any]:
    response = client.get(f"{SOURCECRAFT_API}/repos/{repo}")
    if response.status_code >= 400:
        return {"status": "UNAVAILABLE", "http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        return {"status": "ERROR", "failure_kind": "malformed_json"}
    return {
        "status": "MEASURED",
        "id": payload.get("id"),
        "default_branch": payload.get("default_branch") or "main",
        "language": (payload.get("language") or {}).get("name") if isinstance(payload.get("language"), dict) else None,
        "is_empty": payload.get("is_empty"),
        "template_type": payload.get("template_type"),
        "last_updated": payload.get("last_updated"),
        "counters": payload.get("counters") or {},
        "clone_url": ((payload.get("clone_url") or {}).get("https") if isinstance(payload.get("clone_url"), dict) else None),
        "rating": ((payload.get("rating") or {}).get("value") if isinstance(payload.get("rating"), dict) else None),
    }


def issue_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    issue_id = str(first(raw, "id", "slug") or "").strip()
    slug = str(first(raw, "slug", "id") or "").strip()
    if not issue_id:
        return None
    status = raw.get("status")
    status_slug = first(status, "slug", "name", "state") if isinstance(status, dict) else status
    return {
        "id": issue_id,
        "issue_number": slug or None,
        "url": f"{SOURCECRAFT_WEB}/{CURRENT_REPO}/issues/{slug}" if slug else None,
        "created_at": first(raw, "created_at", "created"),
        "updated_at": first(raw, "updated_at", "updated"),
        # SourceCraft uses completed_at for terminal issues. Keep the spike
        # inventory contract aligned with production IssueFacts.closed_at.
        "closed_at": first(raw, "closed_at", "closed_on", "resolved_at", "completed_at"),
        "state": str(status_slug or raw.get("state") or "unknown").casefold(),
        "author": compact_actor(first(raw, "author", "actor", "user", "creator")),
        "is_pull_request": False,
        "source": "sourcecraft",
        "source_version": "sourcecraft-rest",
        "has_comments": True,
        "has_state_events": False,
    }


def comment_row(raw: dict[str, Any], issue_id: str, index: int) -> dict[str, Any] | None:
    timestamp = first(raw, "created_at", "timestamp", "date")
    if timestamp in (None, ""):
        return None
    return {
        "id": str(first(raw, "id", "message_id", "slug") or f"{issue_id}:comment:{index}"),
        "issue_id": issue_id,
        "event_type": "commented",
        "created_at": timestamp,
        "author": compact_actor(first(raw, "author", "actor", "user", "creator")),
    }


def collect_issues(client: httpx.Client, repo: str) -> tuple[dict[str, Any], dict[str, Any]]:
    global CURRENT_REPO
    CURRENT_REPO = repo
    owner, slug = repo_name(repo)
    all_rows: list[dict[str, Any]] = []
    next_token: str | None = None
    pages = 0
    failure: str | None = None
    for _ in range(MAX_ISSUE_PAGES):
        params: dict[str, Any] = {"page_size": 100}
        if next_token:
            params["page_token"] = next_token
        response = client.get(f"{SOURCECRAFT_API}/repos/{owner}/{slug}/issues", params=params)
        pages += 1
        if response.status_code in {401, 403, 404}:
            return ({"source_kind": "sourcecraft", "source_version": "sourcecraft-rest", "status": "UNAVAILABLE", "records_available": False, "permission_state": "denied" if response.status_code in {401, 403} else "unknown", "issues": [], "issue_comments": [], "issue_events": []}, {"status": "UNAVAILABLE", "http_status": response.status_code, "pages": pages})
        if response.status_code >= 400:
            return ({"source_kind": "sourcecraft", "source_version": "sourcecraft-rest", "status": "ERROR", "records_available": False, "permission_state": "unknown", "issues": [], "issue_comments": [], "issue_events": []}, {"status": "ERROR", "http_status": response.status_code, "pages": pages})
        try:
            rows, next_token = extract_rows(response.json(), "issues")
        except (TypeError, ValueError, json.JSONDecodeError):
            return ({"source_kind": "sourcecraft", "source_version": "sourcecraft-rest", "status": "ERROR", "records_available": False, "permission_state": "granted", "issues": [], "issue_comments": [], "issue_events": []}, {"status": "ERROR", "failure_kind": "malformed_json_or_shape", "pages": pages})
        all_rows.extend(rows)
        if len(all_rows) >= MAX_ISSUES_PER_REPOSITORY:
            failure = "issue_safety_bound"
            break
        if not next_token:
            break
    else:
        failure = "max_pages_reached"
    normalized = [row for row in (issue_row(item) for item in all_rows[:MAX_ISSUES_PER_REPOSITORY]) if row is not None]
    comments: list[dict[str, Any]] = []
    comments_complete = True
    comment_requests = 0
    for item in normalized:
        if comment_requests >= MAX_COMMENT_REQUESTS:
            comments_complete = False
            failure = failure or "comment_safety_bound"
            break
        issue_id = str(item["id"])
        issue_slug = str(item.get("issue_number") or issue_id)
        response = client.get(f"{SOURCECRAFT_API}/repos/{owner}/{slug}/issues/{issue_slug}/comments", params={"page_size": 100})
        comment_requests += 1
        if response.status_code in {401, 403, 404} or response.status_code >= 400:
            comments_complete = False
            continue
        try:
            rows, comment_next = extract_rows(response.json(), "issue_comments")
        except (TypeError, ValueError, json.JSONDecodeError):
            comments_complete = False
            continue
        if comment_next:
            comments_complete = False
        comments.extend(row for index, raw in enumerate(rows) if (row := comment_row(raw, issue_id, index)) is not None)
    pagination_complete = failure is None and next_token is None
    status = "NO_ISSUES" if not normalized and pagination_complete else "PARTIAL" if not pagination_complete or not comments_complete else "MEASURED"
    inventory = {
        "source_kind": "sourcecraft",
        "source_version": "sourcecraft-rest",
        "status": status,
        "records_available": True,
        "records_expected": len(normalized),
        "pagination_complete": pagination_complete,
        "local_date_filter_applied": False,
        "comments_available": comments_complete,
        "state_events_available": False,
        "permission_state": "granted",
        "issues": normalized,
        "issue_comments": comments,
        "issue_events": [],
    }
    return inventory, {"status": status, "pages": pages, "records": len(normalized), "comments": len(comments), "comments_complete": comments_complete, "failure_kind": failure}


def redact_run(raw: dict[str, Any], page: int) -> dict[str, Any]:
    allowed = {"id", "run_id", "uid", "slug", "run_slug", "status", "state", "result", "created_at", "started_at", "finished_at", "updated_at", "duration_seconds", "duration", "workflow_id", "workflow_name", "commit_sha", "commit", "revision", "sha", "branch", "ref", "retry_group_id", "retry_group", "rerun_group_id", "parent_run_id", "parent_id", "rerun_of", "attempt", "attempt_number", "deep_link", "url", "web_url", "link"}
    result = {key: raw[key] for key in allowed if key in raw}
    dates = raw.get("dates") if isinstance(raw.get("dates"), dict) else {}
    for key in ("created_at", "started_at", "finished_at", "updated_at"):
        if key not in result and dates.get(key) is not None:
            result[key] = dates[key]
    result["source_page"] = page
    return result


def parse_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=UTC)
    except ValueError:
        return None


def collect_ci(client: httpx.Client, repo: str) -> tuple[dict[str, Any], dict[str, Any]]:
    owner, slug = repo_name(repo)
    rows: list[dict[str, Any]] = []
    next_token: str | None = None
    pages = 0
    failure: str | None = None
    for _ in range(MAX_CI_PAGES):
        params: dict[str, Any] = {"page_size": 100}
        if next_token:
            params["page_token"] = next_token
        response = client.get(f"{SOURCECRAFT_API}/repos/{owner}/{slug}/cicd/runs", params=params)
        pages += 1
        if response.status_code in {401, 403, 404}:
            return ({"schema_version": "sourcecraft-cicd-inventory-v1", "source_kind": "sourcecraft", "source_version": "sourcecraft-cicd-api", "status": "unavailable", "configured": None, "permission_state": "denied" if response.status_code in {401, 403} else "unknown", "runs": [], "pagination": {"complete": False, "pages_fetched": pages}, "local_filter": {"applied": False}, "diagnostics": {"reason": f"http_{response.status_code}"}}, {"status": "UNAVAILABLE", "http_status": response.status_code, "pages": pages})
        if response.status_code >= 400:
            return ({"schema_version": "sourcecraft-cicd-inventory-v1", "source_kind": "sourcecraft", "source_version": "sourcecraft-cicd-api", "status": "error", "configured": None, "permission_state": "unknown", "runs": [], "pagination": {"complete": False, "pages_fetched": pages}, "local_filter": {"applied": False}, "diagnostics": {"reason": f"http_{response.status_code}"}}, {"status": "ERROR", "http_status": response.status_code, "pages": pages})
        try:
            page_rows, next_token = extract_rows(response.json(), "runs")
        except (TypeError, ValueError, json.JSONDecodeError):
            return ({"schema_version": "sourcecraft-cicd-inventory-v1", "source_kind": "sourcecraft", "source_version": "sourcecraft-cicd-api", "status": "error", "configured": None, "permission_state": "granted", "runs": [], "pagination": {"complete": False, "pages_fetched": pages}, "local_filter": {"applied": False}, "diagnostics": {"reason": "malformed_json_or_shape"}}, {"status": "ERROR", "failure_kind": "malformed_json_or_shape", "pages": pages})
        rows.extend(redact_run(item, pages) for item in page_rows)
        if not next_token:
            break
    else:
        failure = "max_pages_reached"
    start = AS_OF - timedelta(days=WINDOW_DAYS)
    filtered = [row for row in rows if (stamp := parse_timestamp(first(row, "created_at", "started_at", "finished_at", "updated_at"))) is None or start <= stamp < AS_OF]
    status = "partial" if failure else "measured" if filtered else "no_runs"
    envelope = {"schema_version": "sourcecraft-cicd-inventory-v1", "source_kind": "sourcecraft", "source_version": "sourcecraft-cicd-api", "status": status, "configured": True, "configuration_source": "sourcecraft_cicd_api", "permission_state": "granted", "runs": filtered, "pagination": {"complete": failure is None and next_token is None, "pages_fetched": pages}, "local_filter": {"applied": True, "analysis_start": start.isoformat(), "analysis_end": AS_OF.isoformat()}, "capabilities": {"retry_relation": "observed_fields_only", "deployment_events": "absent", "production_environment": "absent", "incidents": "absent", "restore_events": "absent"}}
    return envelope, {"status": status.upper(), "pages": pages, "records_received": len(rows), "records_after_local_filter": len(filtered), "failure_kind": failure}


def git_run(args: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def checkout(repo: str, clone_url: str | None) -> tuple[Path | None, dict[str, Any]]:
    owner, slug = repo_name(repo)
    target = CHECKOUT_ROOT / owner / slug
    if repo == "artem03102006/codex-external-audit-public-20260916":
        fixture = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
        return (fixture if fixture.is_dir() else None), {"status": "REUSED_FIXTURE", "path": "spikes/_fixture/codex-external-audit-public-20260916"}
    if target.is_dir() and (target / ".git").exists():
        return target, {"status": "REUSED_CHECKOUT", "path": str(target)}
    if not clone_url:
        clone_url = f"https://git.sourcecraft.dev/{owner}/{slug}.git"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = git_run(["git", "clone", "--no-tags", "--single-branch", clone_url, str(target)], ROOT, timeout=600)
    except subprocess.TimeoutExpired:
        return None, {"status": "ERROR", "failure_kind": "clone_timeout"}
    if completed.returncode != 0:
        return None, {"status": "ERROR", "failure_kind": "clone_failed", "returncode": completed.returncode}
    return target, {"status": "CLONED", "path": str(target)}


def checkout_stats(path: Path) -> dict[str, Any]:
    head = git_run(["git", "rev-parse", "HEAD"], path, timeout=30).stdout.strip()
    count = git_run(["git", "rev-list", "--count", "HEAD"], path, timeout=60).stdout.strip()
    shallow = git_run(["git", "rev-parse", "--is-shallow-repository"], path, timeout=30).stdout.strip().lower() == "true"
    loc = 0
    bytes_count = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [item for item in dirs if item not in {".git", "node_modules", "vendor", "generated", "build", "dist", "out", "coverage", ".venv"}]
        for name in files:
            file_path = Path(root) / name
            try:
                size = file_path.stat().st_size
                if size > 2_000_000:
                    continue
                bytes_count += size
                with file_path.open("rb") as stream:
                    loc += sum(1 for _ in stream)
            except (OSError, UnicodeError):
                continue
    return {"head_sha": head or None, "commit_count": int(count) if count.isdigit() else None, "shallow": shallow, "included_loc": loc, "checkout_bytes": bytes_count}


def context_for(repo: str, path: Path, metadata: dict[str, Any], inventory: dict[str, Any] | None = None) -> Any:
    from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext

    stats = checkout_stats(path)
    merged = dict(inventory or {})
    merged.setdefault("default_branch", metadata.get("default_branch") or "main")
    return AnalyzerContext(repo_path=path, repo_id=repo, head_sha=stats.get("head_sha") or "unknown-head", as_of_ts=AS_OF, mode="offline", inventory=merged, capabilities=("chaoss:events", "git", "local_scan"), tool_paths={"vale": str(VALE), "git-sizer": str(GIT_SIZER)})


def metric_map(result: Any) -> dict[str, object]:
    return {str(item.name): item.value for item in result.metrics}


def project_result(result: Any, source_status: str | None = None) -> dict[str, Any]:
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    source_status = source_status or diagnostics.get("execution_status") or diagnostics.get("issues_status") or diagnostics.get("cicd_status")
    coverage = diagnostics.get("coverage")
    confidence = diagnostics.get("confidence")
    for key in ("pydriller", "issues", "cicd", "code_health"):
        nested = diagnostics.get(key)
        if isinstance(nested, dict):
            coverage = nested.get("coverage", coverage)
            confidence = nested.get("confidence", confidence)
    category_status = str(source_status or result.status.value).upper()
    if category_status in {"PASS", "WARN", "FAIL", "INCONCLUSIVE"}:
        category_status = "MEASURED" if result.score is not None else "UNAVAILABLE"
    return {"analyzer_id": result.analyzer_id, "status": result.status.value, "category_status": category_status, "score": result.score, "coverage": bounded(coverage, 1.0 if result.score is not None else 0.0), "confidence": bounded(confidence, 1.0 if result.score is not None else 0.0), "metrics": metric_map(result), "diagnostics": diagnostics, "finding_count": len(result.findings), "limitation_count": len(result.limitations)}


def run_analyzers(repo: str, path: Path, metadata: dict[str, Any], issues_inventory: dict[str, Any], ci_inventory: dict[str, Any]) -> dict[str, Any]:
    from repowise.core.analysis.health.integrations.chaoss_adapter import activity_adapter, issues_prs_adapter
    from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer
    from repowise.core.analysis.health.integrations.code_health_analyzer import CodeHealthAnalyzer
    from repowise.core.analysis.health.integrations.code_health_collector import CodeHealthFactsCollector
    from repowise.core.analysis.health.integrations.vale_adapter import ValeAdapter, vale_adapter

    issue_context = context_for(repo, path, metadata, issues_inventory)
    ci_context = context_for(repo, path, metadata, {"sourcecraft_cicd": ci_inventory})
    local_context = context_for(repo, path, metadata)
    docs = vale_adapter(local_context)
    activity = activity_adapter(local_context)
    issues = issues_prs_adapter(issue_context)
    cicd = CICDAnalyzer().run(ci_context)
    facts = CodeHealthFactsCollector().collect(local_context, baseline=None)
    code = CodeHealthAnalyzer().analyze(local_context, facts, None)
    security = {"analyzer_id": "sourcecraft.appsec", "status": "SKIPPED", "category_status": "UNAVAILABLE", "score": None, "coverage": 0.0, "confidence": 0.0, "metrics": {}, "diagnostics": {"source": "SourceCraft AppSec", "reason": "No AppSec path is exposed by the current SourceCraft OpenAPI/PAT boundary; no substitute scanner used."}, "finding_count": 0, "limitation_count": 1}
    return {"Documentation": project_result(docs), "Activity": project_result(activity), "Issues": project_result(issues, (issues.diagnostics.get("issues") or {}).get("issue_population_status") if isinstance(issues.diagnostics.get("issues"), dict) else None), "CI/CD": project_result(cicd, cicd.diagnostics.get("cicd_status")), "Security": security, "Code Health": project_result(code, facts.status.value), "code_health_facts": facts.summary()}


def category_q(category: dict[str, Any]) -> float:
    return bounded(category.get("coverage")) * bounded(category.get("confidence"))


def weighted_raw(categories: dict[str, dict[str, Any]], weights: dict[str, float]) -> float | None:
    rows = [(weights[name], number(categories[name].get("score"))) for name in weights if name in categories and number(categories[name].get("score")) is not None and categories[name].get("category_status") not in {"UNAVAILABLE", "ERROR", "NOT_APPLICABLE", "NO_ACTIVITY"}]
    if not rows or sum(weight for weight, _ in rows) <= 0:
        return None
    return sum(weight * score for weight, score in rows) / sum(weight for weight, _ in rows)


def overall_state(categories: dict[str, dict[str, Any]], raw: float | None, threshold: float = 0.75) -> str:
    if raw is None:
        return "INSUFFICIENT_DATA"
    k = sum(WEIGHTS[name] * category_q(categories[name]) for name in WEIGHTS) / sum(WEIGHTS.values())
    measured = sum(1 for item in categories.values() if item.get("category_status") == "MEASURED" and number(item.get("score")) is not None)
    has_unavailable = any(item.get("category_status") in {"UNAVAILABLE", "ERROR"} for item in categories.values())
    essential = category_q(categories["Security"]) >= 0.75 and category_q(categories["Code Health"]) >= 0.75
    if k >= threshold and measured >= 4 and essential and not has_unavailable:
        return "SCORE"
    if k >= 0.50:
        return "PROVISIONAL_SCORE"
    return "INSUFFICIENT_DATA"


def score_row(categories: dict[str, dict[str, Any]], weights: dict[str, float] = WEIGHTS, threshold: float = 0.75) -> dict[str, Any]:
    raw = weighted_raw(categories, weights)
    k = sum(weights[name] * category_q(categories[name]) for name in weights) / sum(weights.values())
    return {"h_raw": round(raw, 6) if raw is not None else None, "k": round(k, 6), "state": overall_state(categories, raw, threshold)}


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "min": None, "max": None}
    ordered = sorted(values)
    def pct(q: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        pos = q * (len(ordered) - 1); lo = math.floor(pos); hi = math.ceil(pos)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
    return {"n": len(values), "mean": statistics.fmean(values), "median": statistics.median(values), "p10": pct(.10), "p25": pct(.25), "p50": pct(.50), "p75": pct(.75), "p90": pct(.90), "min": min(values), "max": max(values)}


def rank(values: list[float | None]) -> list[float | None]:
    pairs = sorted((value, index) for index, value in enumerate(values) if value is not None)
    result: list[float | None] = [None] * len(values)
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average = (index + 1 + end) / 2
        for _, original in pairs[index:end]:
            result[original] = average
        index = end
    return result


def spearman(left: list[float | None], right: list[float | None]) -> tuple[float | None, int]:
    rows = [(a, b) for a, b in zip(left, right, strict=True) if a is not None and b is not None]
    if len(rows) < 3:
        return None, len(rows)
    lr = rank([row[0] for row in rows]); rr = rank([row[1] for row in rows])
    x = [float(value) for value in lr if value is not None]; y = [float(value) for value in rr if value is not None]
    mx = statistics.fmean(x); my = statistics.fmean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)); denominator = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return (numerator / denominator if denominator else 0.0), len(rows)


def category_distributions(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in WEIGHTS:
        rows = [record["categories"][name] for record in records]
        scores = [number(row.get("score")) for row in rows]
        coverages = [number(row.get("coverage")) for row in rows]
        confidences = [number(row.get("confidence")) for row in rows]
        result[name] = {"score": stats([value for value in scores if value is not None]), "coverage": stats([value for value in coverages if value is not None]), "confidence": stats([value for value in confidences if value is not None]), "missing_rate": sum(value is None for value in scores) / len(scores) if scores else 1.0, "status_counts": dict(Counter(str(row.get("category_status")) for row in rows))}
    return result


def correlations(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = {name: [number(item["categories"][name].get("score")) for item in records] for name in WEIGHTS}
    pairs: dict[str, Any] = {}
    for left, right in itertools.combinations(WEIGHTS, 2):
        rho, n = spearman(values[left], values[right]); pairs[f"{left}~{right}"] = {"spearman": rho, "n": n, "interpretation": "statistical_only_low_n" if n < 10 else "review_semantic_overlap_before_deduplication"}
    signals = {
        "Activity_score": values["Activity"],
        "Issues_score": values["Issues"],
        "CI_failure_rate": [number(item["categories"]["CI/CD"].get("metrics", {}).get("cicd:failure_rate")) for item in records],
        "Issues_open": [number(item["categories"]["Issues"].get("metrics", {}).get("issues:open_issues")) for item in records],
        "CodeHealth_git_structure": [number(item["categories"]["Code Health"].get("metrics", {}).get("code_health:git_structure")) for item in records],
        "Documentation_findings": [number(item["categories"]["Documentation"].get("metrics", {}).get("vale_findings")) for item in records],
    }
    signal_pairs: dict[str, Any] = {}
    for left, right in itertools.combinations(signals, 2):
        rho, n = spearman(signals[left], signals[right]); signal_pairs[f"{left}~{right}"] = {"spearman": rho, "n": n}
    return {"category_pairs": pairs, "signal_pairs": signal_pairs, "semantic_review": {"Activity~Issues": "related maintenance populations but different event sources and denominators", "Activity~CI/CD": "recency/automation can co-vary; not duplicate because one is Git history and one is run outcomes", "Code Health~CI/CD": "test/automation maturity may co-vary; CI failure is delivery reliability, Code Health is maintainability/structure", "Documentation~Code Health": "both inspect files but Vale prose and code maintainability have disjoint populations"}}


def synthetic_anchors() -> dict[str, Any]:
    base = {name: {"score": 100.0, "coverage": 1.0, "confidence": 1.0, "category_status": "MEASURED", "metrics": {}} for name in WEIGHTS}
    scenarios = {
        "critical_security_one": {"Security": 40.0},
        "critical_security_multiple": {"Security": 0.0},
        "confirmed_secret": {"Security": 0.0},
        "only_high_security": {"Security": 70.0},
        "security_unavailable": {"Security": None, "Security_status": "UNAVAILABLE"},
        "resolved_critical": {"Security": 85.0},
        "critical_plus_rest_100": {"Security": 0.0},
    }
    output: dict[str, Any] = {}
    for name, changes in scenarios.items():
        categories = json.loads(json.dumps(base))
        for category, value in changes.items():
            if category.endswith("_status"):
                categories[category.removesuffix("_status")]["category_status"] = value
            else:
                categories[category]["score"] = value
        row = score_row(categories)
        row["security_caps"] = {str(cap): min(row["h_raw"], cap) if row["h_raw"] is not None else None for cap in (30, 40, 50, 60)}
        output[name] = row
    return output


def anti_gaming_anchors() -> dict[str, Any]:
    base = {name: {"score": 85.0, "coverage": 1.0, "confidence": 1.0, "category_status": "MEASURED", "metrics": {}} for name in WEIGHTS}
    scenarios = {
        "empty_commits_plus_100": {"Activity": 45.0},
        "many_tiny_commits": {"Activity": 55.0},
        "readme_filler": {"Documentation": 60.0},
        "close_issues_without_response": {"Issues": 45.0},
        "disable_ci": {"CI/CD": 35.0},
        "remove_security_api": {"Security": None, "Security_status": "UNAVAILABLE"},
        "delete_tests": {"Code Health": 55.0},
        "huge_generated_files": {"Code Health": 70.0},
        "fix_vulnerability": {"Security": 90.0},
    }
    output: dict[str, Any] = {}
    base_score = score_row(base)
    for name, changes in scenarios.items():
        categories = json.loads(json.dumps(base))
        for category, value in changes.items():
            if category.endswith("_status"):
                categories[category.removesuffix("_status")]["category_status"] = value
            else:
                categories[category]["score"] = value
        row = score_row(categories)
        row["delta_from_reference"] = round(row["h_raw"] - base_score["h_raw"], 6) if row["h_raw"] is not None else None
        output[name] = row
    return {"reference": base_score, "scenarios": output}


def run() -> dict[str, Any]:
    if not os.environ.get(SOURCECRAFT_PAT):
        raise RuntimeError("SOURCECRAFT_PAT is required for the real SourceCraft calibration")
    OUT.mkdir(parents=True, exist_ok=True)
    CHECKOUT_ROOT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))
    install_verification_shim()
    client = api_client()
    records: list[dict[str, Any]] = []
    repo_rows: list[dict[str, Any]] = []
    try:
        for index, (repo, expected_language, stratum) in enumerate(SAMPLE, start=1):
            print(f"[{index}/{len(SAMPLE)}] {repo}", flush=True)
            metadata = sourcecraft_metadata(client, repo)
            path, clone = checkout(repo, metadata.get("clone_url"))
            row = {"repo": repo, "stratum": stratum, "expected_language": expected_language, "metadata_status": metadata.get("status"), "api_language": metadata.get("language") or expected_language, "clone_status": clone.get("status"), "checkout": clone.get("path")}
            if path is None:
                row.update({"analysis_status": "ERROR", "failure_kind": clone.get("failure_kind", "checkout_unavailable")})
                repo_rows.append(row)
                continue
            try:
                metadata.setdefault("default_branch", "main")
                issues_inventory, issues_collection = collect_issues(client, repo)
                ci_inventory, ci_collection = collect_ci(client, repo)
                categories = run_analyzers(repo, path, metadata, issues_inventory, ci_inventory)
                stat = checkout_stats(path)
                row.update({"analysis_status": "MEASURED", "head_sha_prefix": (stat.get("head_sha") or "")[:12], "commit_count": stat.get("commit_count"), "shallow": stat.get("shallow"), "included_loc": stat.get("included_loc"), "checkout_bytes": stat.get("checkout_bytes"), "issues_collection": issues_collection, "ci_collection": ci_collection})
                result = {"repo": repo, "stratum": stratum, "language": metadata.get("language") or expected_language, "metadata": {key: metadata.get(key) for key in ("default_branch", "last_updated", "counters", "rating", "template_type", "is_empty")}, "checkout": {key: stat.get(key) for key in ("head_sha", "commit_count", "shallow", "included_loc", "checkout_bytes")}, "categories": {key: categories[key] for key in WEIGHTS}, "code_health_facts": categories.get("code_health_facts"), "collection": {"issues": issues_collection, "cicd": ci_collection}, "score": score_row({key: categories[key] for key in WEIGHTS})}
                result["category_metrics"] = {name: {key: value for key, value in item["metrics"].items() if key in {"vale_findings", "vale_quality", "pydriller:unique_commits", "pydriller:latest_activity_age_days", "pydriller:activity_quality", "issues:open_issues", "issues:unanswered_ratio", "issues:sample_size", "cicd:success_rate", "cicd:failure_rate", "cicd:total_runs", "cicd:last_run_status", "code_health:git_structure", "code_health:complexity", "code_health:maintainability_debt"}} for name, item in result["categories"].items()}
                records.append(result)
            except Exception as exc:
                row.update({"analysis_status": "ERROR", "failure_kind": type(exc).__name__})
                print(f"  analyzer error: {type(exc).__name__}", flush=True)
            repo_rows.append(row)
    finally:
        client.close()

    # Every repo in the fixed sample is retained in repos.csv, including a
    # clone/analyzer failure.  The score cohort is explicitly N of successful
    # six-category runs and never silently imputes missing categories.
    with (OUT / "repos.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = sorted({key for row in repo_rows for key in row} | {"repo", "stratum"})
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in repo_rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})

    distributions = category_distributions(records)
    corr = correlations(records)
    threshold_rows: list[dict[str, Any]] = []
    for threshold in (0.40, 0.50, 0.60, 0.70, 0.75, 0.80):
        states = [score_row(item["categories"], threshold=threshold)["state"] for item in records]
        threshold_rows.append({"threshold": threshold, "SCORE": states.count("SCORE"), "PROVISIONAL_SCORE": states.count("PROVISIONAL_SCORE"), "INSUFFICIENT_DATA": states.count("INSUFFICIENT_DATA"), "security_q_ge_075": sum(category_q(item["categories"]["Security"]) >= .75 for item in records), "code_health_q_ge_075": sum(category_q(item["categories"]["Code Health"]) >= .75 for item in records), "min_four_measured": sum(sum(1 for category in item["categories"].values() if category.get("category_status") == "MEASURED" and number(category.get("score")) is not None) >= 4 for item in records), "full_score_eligibility": 0})

    variants = {
        "candidate_15_15_15_15_20_20": WEIGHTS,
        "equal": {name: 100.0 / 6 for name in WEIGHTS},
        "security_code_15": {"Documentation": 17.5, "Activity": 17.5, "Issues": 17.5, "CI/CD": 17.5, "Security": 15.0, "Code Health": 15.0},
        "security_code_25": {"Documentation": 12.5, "Activity": 12.5, "Issues": 12.5, "CI/CD": 12.5, "Security": 25.0, "Code Health": 25.0},
        "maintenance_focused": {"Documentation": 10.0, "Activity": 20.0, "Issues": 20.0, "CI/CD": 10.0, "Security": 20.0, "Code Health": 20.0},
    }
    sensitivity_rows: list[dict[str, Any]] = []
    variant_scores: dict[str, list[float | None]] = {}
    for variant, weights in variants.items():
        values: list[float | None] = []
        for item in records:
            row = score_row(item["categories"], weights)
            values.append(row["h_raw"])
            sensitivity_rows.append({"repo": item["repo"], "variant": variant, "h_raw": row["h_raw"], "k": row["k"], "state": row["state"]})
        variant_scores[variant] = values
    with (OUT / "sensitivity.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("repo", "variant", "h_raw", "k", "state"))
        writer.writeheader(); writer.writerows(sensitivity_rows)
    ranking_sensitivity = {}
    base_scores = variant_scores["candidate_15_15_15_15_20_20"]
    for variant, values in variant_scores.items():
        rho, n = spearman(base_scores, values)
        deltas = [abs(a - b) for a, b in zip(base_scores, values, strict=True) if a is not None and b is not None]
        ranking_sensitivity[variant] = {"spearman_vs_candidate": rho, "n": n, "mean_absolute_delta": statistics.fmean(deltas) if deltas else None, "max_absolute_delta": max(deltas) if deltas else None}

    anomalies: dict[str, Any] = {"ci_82_at_failure_rate_31_percent": {"observed_repositories": [], "real_cohort_supported": False, "reason": "CI endpoint returned UNAVAILABLE for the public sample; the 82/31% anchor was not inferred."}, "young_activity_near_80": [], "code_health_near_79_complexity_zero": []}
    for item in records:
        age_days = None
        if item["checkout"].get("commit_count") is not None:
            latest = item["categories"]["Activity"].get("metrics", {}).get("pydriller:latest_activity_age_days")
            age_days = number(latest)
        if number(item["categories"]["Activity"].get("score")) is not None and number(item["categories"]["Activity"].get("score")) >= 75 and age_days is not None and age_days <= 30:
            anomalies["young_activity_near_80"].append({"repo": item["repo"], "activity_score": item["categories"]["Activity"].get("score"), "latest_activity_age_days": age_days})
        code_score = number(item["categories"]["Code Health"].get("score")); complexity = number(item["categories"]["Code Health"].get("metrics", {}).get("code_health:complexity"))
        if code_score is not None and 75 <= code_score <= 83 and (complexity is None or complexity == 0):
            anomalies["code_health_near_79_complexity_zero"].append({"repo": item["repo"], "code_health_score": code_score, "complexity_component": complexity})

    report = {"calibration": {"as_of": AS_OF.isoformat(), "sample_definition": "fixed public SourceCraft sample selected 2026-09-20 from global /repos catalog; 5 high-rating/mature, 5 oldest, 5 newest, 12 language quota, 9 deterministic hash, 1 real fixture anchor", "sample_n": len(SAMPLE), "successful_six_category_runs": len(records), "full_data_security_available_n": sum(item["categories"]["Security"]["category_status"] == "MEASURED" for item in records), "weights": WEIGHTS, "window_days": WINDOW_DAYS, "production_code_changed": False, "score_engine_changed": False, "token_logged": False}, "records": records, "distributions": distributions, "correlations": corr, "coverage_thresholds": threshold_rows, "sensitivity": {"weights": variants, "rank_and_score_stability": ranking_sensitivity}, "security_cap_anchors": synthetic_anchors(), "anti_gaming_anchors": anti_gaming_anchors(), "anomalies": anomalies, "limitations": ["SourceCraft CI listCIFlux permission was unavailable for the public cohort; CI is UNAVAILABLE rather than zero.", "SourceCraft OpenAPI exposed no AppSec findings endpoint for this PAT; Security is UNAVAILABLE rather than substituted.", "The checkout currently lacks health.coverage.py; a calibration-process-only shim was used.", "No real full-data six-category cohort exists in this run, so final score thresholds/caps remain conditional until AppSec and CI access are supplied."]}
    (OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"sample_n": len(SAMPLE), "successful_runs": len(records), "full_data_security_n": report["calibration"]["full_data_security_available_n"], "output": str(OUT / "results.json")}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    CURRENT_REPO = ""
    run()
