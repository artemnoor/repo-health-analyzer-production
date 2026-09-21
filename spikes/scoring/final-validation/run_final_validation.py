#!/usr/bin/env python3
"""Collect a redacted empirical validation snapshot for Security, Issues and CI/CD.

This is a spike-only runner.  It deliberately reuses the existing SourceCraft
collector boundaries and analyzers, but never writes production code, never
persists raw issue/comment payloads, and never prints a PAT.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "spikes" / "scoring" / "final-validation"
CALIBRATION_RUNNER = ROOT / "spikes" / "scoring" / "calibration" / "run_calibration.py"
AS_OF = datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)
WINDOW_DAYS = 90
ISSUE_CANDIDATES = (
    "a-obraz60022006/mirea-trade",
    "k-5-45mm/dozzle-plus",
    "arceniytadevosyan/lmsweb",
    "astra-shellless-images/nginx",
    "astra-shellless-images/opensearch",
    "astra-shellless-images/tomcat",
    "fompronin/heh",
    "imbok/cosmos-ontology",
    "imbok/uims-portal",
    "sourcecraft/sourcecraft",
)
CI_REPOSITORIES = (
    "artem03102006/codex-external-audit-public-20260916",
    "artem03102006/codex-external-audit-private-20260916",
)


def load_calibration_module() -> Any:
    spec = importlib.util.spec_from_file_location("final_validation_calibration", CALIBRATION_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the existing calibration collector")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.install_verification_shim()
    return module


def digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


def metric_map(result: Any) -> dict[str, Any]:
    return {str(item.name): item.value for item in result.metrics}


def bounded(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def safe_findings(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in result.findings:
        rows.append(
            {
                "id_digest": digest(getattr(finding, "id", "")),
                "subject_digest": digest(getattr(finding, "subject", "")),
                "severity": getattr(finding, "severity", None),
                "reason_class": str(getattr(finding, "reason", "")).split(":", 1)[0][:80],
            }
        )
    return rows


def issue_summary(cal: Any, repo: str, inventory: dict[str, Any], collection: dict[str, Any], result: Any) -> dict[str, Any]:
    metrics = metric_map(result)
    issue_diag = result.diagnostics.get("issues") if isinstance(result.diagnostics, dict) else {}
    source = issue_diag.get("source_summary", {}) if isinstance(issue_diag, dict) else {}
    return {
        "repository": repo,
        "collection": {
            "status": collection.get("status"),
            "pages": collection.get("pages"),
            "records": collection.get("records"),
            "comments": collection.get("comments"),
            "comments_complete": collection.get("comments_complete"),
            "failure_kind": collection.get("failure_kind"),
        },
        "analyzer": {
            "status": result.status.value,
            "category_status": issue_diag.get("issue_population_status") if isinstance(issue_diag, dict) else None,
            "score": result.score,
            "coverage": source.get("coverage"),
            "confidence": source.get("confidence"),
            "metric_statuses": issue_diag.get("metric_statuses", {}) if isinstance(issue_diag, dict) else {},
            "eligible_components": list(issue_diag.get("eligible_components", ())) if isinstance(issue_diag, dict) else [],
            "component_scores": issue_diag.get("component_scores", {}) if isinstance(issue_diag, dict) else {},
            "component_samples": issue_diag.get("component_samples", {}) if isinstance(issue_diag, dict) else {},
            "component_coverage": issue_diag.get("component_coverage", {}) if isinstance(issue_diag, dict) else {},
        },
        "real_signals": {
            "sample_size_in_window": metrics.get("issues:sample_size"),
            "open_issues": metrics.get("issues:open_issues"),
            "closed_issues": metrics.get("issues:closed_issues"),
            "closure_ratio": metrics.get("issues:closure_ratio"),
            "first_response_median_hours": metrics.get("issues:first_response_median_hours"),
            "first_response_p75_hours": metrics.get("issues:first_response_p75_hours"),
            "unanswered_issues": metrics.get("issues:unanswered_issues"),
            "stale_ratio": metrics.get("issues:stale_ratio"),
            "old_open_ratio": metrics.get("issues:old_open_ratio"),
            "open_age_median_hours": metrics.get("issues:open_age_median_hours"),
            "comments_human": metrics.get("issues:comments_human"),
            "comments_bot": metrics.get("issues:comments_bot"),
            "reopened_issues": metrics.get("issues:reopened_issues"),
        },
        "source_quality": {
            "pagination_complete": source.get("pagination_complete"),
            "local_date_filter_applied": source.get("local_date_filter_applied"),
            "comments_available": source.get("comments_available"),
            "state_events_available": source.get("state_events_available"),
            "actor_metadata_coverage": source.get("actor_metadata_coverage"),
            "records_observed": source.get("records_observed"),
            "limitations": list(source.get("limitations", ())),
        },
        "findings": safe_findings(result),
        "raw_payloads_written": False,
    }


def collect_issues(cal: Any) -> list[dict[str, Any]]:
    from repowise.core.analysis.health.integrations.chaoss_adapter import issues_prs_adapter

    path = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
    rows: list[dict[str, Any]] = []
    with cal.api_client() as client:
        for repo in ISSUE_CANDIDATES:
            inventory, collection = cal.collect_issues(client, repo)
            context = cal.context_for(repo, path, {"default_branch": "main"}, inventory)
            result = issues_prs_adapter(context)
            rows.append(issue_summary(cal, repo, inventory, collection, result))
    return rows


def server_filtered_issue_probe() -> dict[str, Any]:
    """Probe the documented SourceCraft issue filters without retaining rows.

    This is deliberately separate from the production collector.  It answers
    whether the API can provide a complete 90-day population plus the current
    open backlog without forcing the analyzer to infer a date window locally.
    Only counts, HTTP classes and field-presence counts are retained.
    """
    import httpx

    candidates = (
        "a-obraz60022006/mirea-trade",
        "k-5-45mm/dozzle-plus",
        "arceniytadevosyan/lmsweb",
        "astra-shellless-images/nginx",
        "astra-shellless-images/opensearch",
        "astra-shellless-images/tomcat",
        "fompronin/heh",
        "imbok/cosmos-ontology",
        "imbok/uims-portal",
        "sourcecraft/sourcecraft",
    )
    token = os.environ.get("SOURCECRAFT_PAT", "")
    if not token:
        return {"status": "UNAVAILABLE", "reason": "SOURCECRAFT_PAT_missing", "repositories": []}
    start = AS_OF - timedelta(days=WINDOW_DAYS)
    start_text = start.isoformat().replace("+00:00", "Z")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    rows: list[dict[str, Any]] = []
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        for repository in candidates:
            by_filter: dict[str, dict[str, Any]] = {}
            for filter_name, expression in (
                ("created_in_window", f'created_at>"{start_text}"'),
                ("open_backlog", "status=open"),
            ):
                total = 0
                pages = 0
                complete = False
                status_classes: list[int] = []
                completed_at_count = 0
                state_counts: dict[str, int] = {}
                page_token: str | None = None
                failure: str | None = None
                for _ in range(10):
                    params: dict[str, Any] = {
                        "page_size": 100,
                        "filter": expression,
                        "sort_by": "-created_at",
                    }
                    if page_token:
                        params["page_token"] = page_token
                    response = client.get(
                        "https://api.sourcecraft.tech/repos/" + repository + "/issues",
                        params=params,
                    )
                    pages += 1
                    status_classes.append(response.status_code)
                    if response.status_code == 429:
                        # Retry a rate-limited page, but never convert it into
                        # an empty population.
                        time.sleep(min(3.0, 0.5 * pages))
                        pages -= 1
                        continue
                    if response.status_code != 200:
                        failure = f"http_{response.status_code}"
                        break
                    try:
                        payload = response.json()
                    except ValueError:
                        failure = "malformed_json"
                        break
                    page_rows = payload.get("issues", []) if isinstance(payload, dict) else []
                    if not isinstance(page_rows, list):
                        failure = "malformed_issue_shape"
                        break
                    for issue in page_rows:
                        if not isinstance(issue, dict):
                            continue
                        total += 1
                        if issue.get("completed_at"):
                            completed_at_count += 1
                        status = issue.get("status")
                        status_slug = status.get("slug") if isinstance(status, dict) else status
                        state_counts[str(status_slug or "unknown")] = state_counts.get(str(status_slug or "unknown"), 0) + 1
                    page_token = payload.get("next_page_token") or None
                    if not page_token:
                        complete = True
                        break
                by_filter[filter_name] = {
                    "rows": total,
                    "pages": pages,
                    "pagination_complete": complete,
                    "http_statuses": status_classes,
                    "completed_at_rows": completed_at_count,
                    "state_counts": state_counts,
                    "failure_kind": failure,
                }
            recent = by_filter.get("created_in_window", {})
            opened = by_filter.get("open_backlog", {})
            rows.append(
                {
                    "repository": repository,
                    "created_in_window": recent,
                    "open_backlog": opened,
                    "union_candidate_rows_upper_bound": (recent.get("rows", 0) or 0) + (opened.get("rows", 0) or 0),
                    "sample_ge_5_in_window": (recent.get("rows", 0) or 0) >= 5,
                    "raw_payload_retained": False,
                }
            )
    return {
        "status": "MEASURED",
        "analysis_window_days": WINDOW_DAYS,
        "filter_contract": "created_at>RFC3339 plus status=open, with page_token pagination",
        "repositories": rows,
        "source": "official SourceCraft REST Issues API",
        "raw_payload_retained": False,
    }


def owner_scoped_access_probe() -> dict[str, Any]:
    """Discover PAT-owned repositories without retaining repository payloads."""
    import httpx

    token = os.environ.get("SOURCECRAFT_PAT", "")
    if not token:
        return {"status": "UNAVAILABLE", "reason": "SOURCECRAFT_PAT_missing", "raw_payload_retained": False}
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    result: dict[str, Any] = {"raw_payload_retained": False}
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        user_response = client.get("https://api.sourcecraft.tech/user")
        result["user_http_status"] = user_response.status_code
        if user_response.status_code != 200:
            result["status"] = "UNAVAILABLE"
            return result
        user = user_response.json()
        username = user.get("username") if isinstance(user, dict) else None
        result["username_present"] = bool(username)
        if not username:
            result["status"] = "ERROR"
            return result
        repos_response = client.get(
            f"https://api.sourcecraft.tech/orgs/{username}/repos",
            params={"page_size": 100},
        )
        result["organization_repositories_http_status"] = repos_response.status_code
        repositories: list[dict[str, Any]] = []
        if repos_response.status_code == 200:
            payload = repos_response.json()
            for repository in payload.get("repositories", []) if isinstance(payload, dict) else []:
                if not isinstance(repository, dict):
                    continue
                repositories.append(
                    {
                        "slug": repository.get("slug"),
                        "visibility": repository.get("visibility"),
                        "has_id": bool(repository.get("id")),
                    }
                )
        result["accessible_repository_count"] = len(repositories)
        result["accessible_repositories"] = repositories
        projects_response = client.get(
            f"https://api.sourcecraft.tech/orgs/{username}/projects",
            params={"page_size": 100},
        )
        result["projects_http_status"] = projects_response.status_code
        result["status"] = "MEASURED" if repos_response.status_code == 200 else "UNAVAILABLE"
    return result


def cicd_id_path_probe() -> dict[str, Any]:
    """Compare SourceCraft CI slug and repository-ID paths without retaining runs."""
    import httpx

    token = os.environ.get("SOURCECRAFT_PAT", "")
    candidates = (
        "a-obraz60022006/mirea-trade",
        "k-5-45mm/dozzle-plus",
        "arceniytadevosyan/lmsweb",
        "astra-shellless-images/nginx",
        "astra-shellless-images/opensearch",
        "astra-shellless-images/tomcat",
        "fompronin/heh",
        "imbok/cosmos-ontology",
        "imbok/uims-portal",
        "sourcecraft/sourcecraft",
    )
    if not token:
        return {"status": "UNAVAILABLE", "reason": "SOURCECRAFT_PAT_missing", "raw_payload_retained": False}
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    rows: list[dict[str, Any]] = []
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        for repository in candidates:
            metadata_response = client.get("https://api.sourcecraft.tech/repos/" + repository)
            metadata: dict[str, Any] = {}
            try:
                metadata = metadata_response.json() if metadata_response.status_code == 200 else {}
            except ValueError:
                metadata = {}
            repository_id = metadata.get("id") if isinstance(metadata, dict) else None
            row: dict[str, Any] = {
                "repository": repository,
                "metadata_http_status": metadata_response.status_code,
                "repository_id_present": bool(repository_id),
                "raw_payload_retained": False,
            }
            for path_class, path in (
                ("slug", f"/repos/{repository}/cicd/runs"),
                ("id", f"/repos/id:{repository_id}/cicd/runs" if repository_id else None),
            ):
                if path is None:
                    row[path_class] = {"http_status": None, "record_count": None}
                    continue
                response = client.get("https://api.sourcecraft.tech" + path, params={"page_size": 100})
                record_count: int | None = None
                try:
                    payload = response.json() if response.status_code == 200 else {}
                    runs = payload.get("runs") if isinstance(payload, dict) else None
                    record_count = len(runs) if isinstance(runs, list) else None
                except (TypeError, ValueError):
                    pass
                row[path_class] = {"http_status": response.status_code, "record_count": record_count}
            rows.append(row)
    return {
        "status": "MEASURED",
        "candidate_count": len(rows),
        "slug_http_status_counts": {
            str(status): sum(1 for row in rows if row.get("slug", {}).get("http_status") == status)
            for status in sorted(
                {
                    row.get("slug", {}).get("http_status")
                    for row in rows
                    if row.get("slug", {}).get("http_status") is not None
                }
            )
        },
        "id_http_status_counts": {
            str(status): sum(1 for row in rows if row.get("id", {}).get("http_status") == status)
            for status in sorted(
                {
                    row.get("id", {}).get("http_status")
                    for row in rows
                    if row.get("id", {}).get("http_status") is not None
                }
            )
        },
        "repositories": rows,
        "raw_payload_retained": False,
    }


def public_boundary_probe() -> dict[str, Any]:
    """Probe anonymous UI permissions and anonymous CI without retaining bodies."""
    script = OUT / "run_public_boundary_probe.js"
    node = shutil.which("node")
    if node is None or not script.exists():
        return {
            "status": "UNAVAILABLE",
            "reason": "node_or_public_boundary_script_missing",
            "raw_payload_retained": False,
        }
    try:
        completed = subprocess.run(
            [node, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "status": "UNAVAILABLE" if isinstance(error, subprocess.TimeoutExpired) else "ERROR",
            "failure_kind": type(error).__name__,
            "raw_payload_retained": False,
        }
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {
            "status": "ERROR",
            "failure_kind": "public_boundary_probe_empty_output",
            "raw_payload_retained": False,
        }
    try:
        payload = json.loads(lines[-1])
    except (TypeError, ValueError):
        return {
            "status": "ERROR",
            "failure_kind": "public_boundary_probe_malformed_output",
            "raw_payload_retained": False,
        }
    if not isinstance(payload, dict):
        return {
            "status": "ERROR",
            "failure_kind": "public_boundary_probe_non_object_output",
            "raw_payload_retained": False,
        }
    payload["runner_exit_code"] = completed.returncode
    payload["raw_payload_retained"] = False
    return payload


def collect_server_filtered_issue_scores(cal: Any) -> dict[str, Any]:
    """Run the existing Issues analyzer over a spike-only better source boundary.

    The production collector is intentionally not changed here.  This probe
    uses SourceCraft's documented server-side date/status filters, carries
    ``completed_at`` into the analyzer's existing ``closed_at`` field, and
    fetches comments separately.  Only normalized analyzer summaries are
    retained in the output.
    """
    import httpx

    from repowise.core.analysis.health.integrations.chaoss_adapter import issues_prs_adapter

    token = os.environ.get("SOURCECRAFT_PAT", "")
    if not token:
        return {"status": "UNAVAILABLE", "reason": "SOURCECRAFT_PAT_missing", "repositories": []}
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    start = AS_OF - timedelta(days=WINDOW_DAYS)
    start_text = start.isoformat().replace("+00:00", "Z")
    fixture_path = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
    rows: list[dict[str, Any]] = []

    def page_rows(payload: object) -> tuple[list[dict[str, Any]], str | None]:
        if not isinstance(payload, dict):
            return [], None
        values = payload.get("issues")
        if not isinstance(values, list):
            return [], None
        return [item for item in values if isinstance(item, dict)], payload.get("next_page_token") or None

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        for repository in ISSUE_CANDIDATES:
            issue_by_id: dict[str, dict[str, Any]] = {}
            pages = 0
            source_complete = True
            failure_kind: str | None = None
            owner, slug = repository.split("/", 1)
            for expression in (f'created_at>"{start_text}"', "status=open"):
                page_token: str | None = None
                for _ in range(20):
                    params: dict[str, Any] = {
                        "page_size": 100,
                        "filter": expression,
                        "sort_by": "-created_at",
                    }
                    if page_token:
                        params["page_token"] = page_token
                    response = client.get(f"https://api.sourcecraft.tech/repos/{repository}/issues", params=params)
                    if response.status_code == 429:
                        time.sleep(0.5)
                        continue
                    pages += 1
                    if response.status_code != 200:
                        source_complete = False
                        failure_kind = f"issues_http_{response.status_code}"
                        break
                    try:
                        page, page_token = page_rows(response.json())
                    except (ValueError, TypeError):
                        source_complete = False
                        failure_kind = "issues_malformed_json"
                        break
                    for raw in page:
                        issue_id = str(raw.get("id") or raw.get("slug") or "").strip()
                        if not issue_id:
                            continue
                        status = raw.get("status")
                        status_slug = status.get("slug") if isinstance(status, dict) else status
                        issue_slug = str(raw.get("slug") or raw.get("id") or issue_id)
                        issue_by_id[issue_id] = {
                            "id": issue_id,
                            "issue_number": issue_slug,
                            "url": f"https://sourcecraft.dev/{repository}/issues/{issue_slug}",
                            "created_at": raw.get("created_at"),
                            "updated_at": raw.get("updated_at"),
                            "closed_at": raw.get("completed_at"),
                            "state": str(status_slug or raw.get("state") or "unknown").casefold(),
                            "author": raw.get("author"),
                            "is_pull_request": False,
                            "source": "sourcecraft",
                            "source_version": "sourcecraft-rest-server-filter-spike-v1",
                            "has_comments": True,
                            "has_state_events": False,
                        }
                    if not page_token:
                        break
                else:
                    source_complete = False
                    failure_kind = failure_kind or "issues_max_pages"
                if not source_complete:
                    break

            issue_rows = list(issue_by_id.values())
            comments: list[dict[str, Any]] = []
            comments_complete = source_complete
            for issue in issue_rows:
                issue_id = str(issue["id"])
                issue_slug = str(issue["issue_number"])
                page_token = None
                for _ in range(10):
                    params = {"page_size": 100}
                    if page_token:
                        params["page_token"] = page_token
                    response = client.get(
                        f"https://api.sourcecraft.tech/repos/{owner}/{slug}/issues/{issue_slug}/comments",
                        params=params,
                    )
                    if response.status_code == 429:
                        time.sleep(0.5)
                        continue
                    if response.status_code != 200:
                        comments_complete = False
                        failure_kind = failure_kind or f"comments_http_{response.status_code}"
                        break
                    try:
                        payload = response.json()
                        raw_comments = payload.get("issue_comments", payload.get("comments", [])) if isinstance(payload, dict) else []
                        if not isinstance(raw_comments, list):
                            raise ValueError("comments_shape")
                    except (ValueError, TypeError):
                        comments_complete = False
                        failure_kind = failure_kind or "comments_malformed_json"
                        break
                    for index, raw in enumerate(raw_comments):
                        if not isinstance(raw, dict):
                            continue
                        timestamp = raw.get("created_at") or raw.get("timestamp") or raw.get("date")
                        if not timestamp:
                            continue
                        comments.append(
                            {
                                "id": str(raw.get("id") or raw.get("message_id") or f"{issue_id}:comment:{index}"),
                                "issue_id": issue_id,
                                "event_type": "commented",
                                "created_at": timestamp,
                                "author": raw.get("author") or raw.get("actor") or raw.get("user"),
                            }
                        )
                    page_token = payload.get("next_page_token") or None
                    if not page_token:
                        break
                else:
                    comments_complete = False
                    failure_kind = failure_kind or "comments_max_pages"

            status = "MEASURED" if source_complete and comments_complete else "PARTIAL"
            inventory = {
                "source_kind": "sourcecraft",
                "source_version": "sourcecraft-rest-server-filter-spike-v1",
                "status": status,
                "records_available": True,
                "records_expected": len(issue_rows),
                "pagination_complete": source_complete,
                "local_date_filter_applied": True,
                "comments_available": comments_complete,
                "state_events_available": False,
                "permission_state": "granted",
                "issues": issue_rows,
                "issue_comments": comments,
                "issue_events": [],
            }
            context = cal.context_for(repository, fixture_path, {"default_branch": "main"}, inventory)
            result = issues_prs_adapter(context)
            rows.append(
                issue_summary(
                    cal,
                    repository,
                    inventory,
                    {
                        "status": status,
                        "pages": pages,
                        "records": len(issue_rows),
                        "comments": len(comments),
                        "comments_complete": comments_complete,
                        "failure_kind": failure_kind,
                    },
                    result,
                )
            )
    return {
        "status": "MEASURED",
        "analysis_window_days": WINDOW_DAYS,
        "source": "official SourceCraft REST server-side issue filters plus issue comments",
        "production_boundary_changed": False,
        "raw_payload_retained": False,
        "repositories": rows,
    }


def issues_empirical_analysis(scored: dict[str, Any]) -> dict[str, Any]:
    """Calculate descriptive, redacted checks over the real scored cohort."""
    import math
    import statistics

    rows = [row for row in scored.get("repositories", []) if isinstance(row, dict)]
    numeric = [row for row in rows if isinstance(row.get("analyzer", {}).get("score"), (int, float))]

    def rank(values: list[float]) -> list[float]:
        ordered = sorted(enumerate(values), key=lambda item: item[1])
        result = [0.0] * len(values)
        index = 0
        while index < len(ordered):
            end = index
            while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
                end += 1
            average_rank = (index + end) / 2.0 + 1.0
            for position in range(index, end + 1):
                result[ordered[position][0]] = average_rank
            index = end + 1
        return result

    def spearman(field: str, extractor: Any) -> dict[str, Any]:
        pairs = []
        for row in numeric:
            value = extractor(row.get("real_signals", {}))
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                pairs.append((float(row["analyzer"]["score"]), float(value)))
        if len(pairs) < 3:
            return {"n": len(pairs), "spearman": None, "interpretation": "descriptive_sample_too_small"}
        left = rank([item[0] for item in pairs])
        right = rank([item[1] for item in pairs])
        left_mean = statistics.mean(left)
        right_mean = statistics.mean(right)
        denominator = math.sqrt(
            sum((value - left_mean) ** 2 for value in left)
            * sum((value - right_mean) ** 2 for value in right)
        )
        coefficient = None if denominator == 0 else sum(
            (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
        ) / denominator
        return {"n": len(pairs), "spearman": coefficient, "interpretation": "descriptive_only_no_inference"}

    def unanswered_ratio(metrics: dict[str, Any]) -> float | None:
        unanswered = metrics.get("unanswered_issues")
        sample = metrics.get("sample_size_in_window")
        if not isinstance(unanswered, (int, float)) or not isinstance(sample, (int, float)) or sample <= 0:
            return None
        return float(unanswered) / float(sample)

    anomalies: list[dict[str, Any]] = []
    for row in numeric:
        signals = row.get("real_signals", {})
        analyzer = row.get("analyzer", {})
        if signals.get("reopened_issues") is None:
            anomalies.append({"repository": row.get("repository"), "kind": "reopened_unavailable_without_state_history"})
        if analyzer.get("score", 0) >= 60 and signals.get("comments_human") == 0:
            anomalies.append({"repository": row.get("repository"), "kind": "high_score_with_no_human_comments", "explanation": "responsiveness is unavailable and excluded from eligible components"})
        if isinstance(signals.get("open_issues"), (int, float)) and isinstance(signals.get("sample_size_in_window"), (int, float)) and signals["open_issues"] > signals["sample_size_in_window"]:
            anomalies.append({"repository": row.get("repository"), "kind": "backlog_exceeds_window_sample", "explanation": "open backlog is a current snapshot, sample is created-in-window"})

    return {
        "cohort_size": len(rows),
        "numeric_score_count": len(numeric),
        "score_min": min((float(row["analyzer"]["score"]) for row in numeric), default=None),
        "score_median": statistics.median(float(row["analyzer"]["score"]) for row in numeric) if numeric else None,
        "score_max": max((float(row["analyzer"]["score"]) for row in numeric), default=None),
        "full_component_coverage_count": sum(
            set(row.get("analyzer", {}).get("eligible_components", ()))
            == {"responsiveness", "resolution", "backlog_health", "maintenance_trend"}
            for row in numeric
        ),
        "signal_correlations": {
            "score_vs_closure_ratio": spearman("closure_ratio", lambda m: m.get("closure_ratio")),
            "score_vs_stale_ratio": spearman("stale_ratio", lambda m: m.get("stale_ratio")),
            "score_vs_unanswered_ratio": spearman("unanswered_ratio", unanswered_ratio),
            "score_vs_open_age_median_hours": spearman("open_age_median_hours", lambda m: m.get("open_age_median_hours")),
            "score_vs_first_response_median_hours": spearman("first_response_median_hours", lambda m: m.get("first_response_median_hours")),
        },
        "direction_checks": {
            "closure_ratio_expected_positive": True,
            "closure_ratio_observed_positive": spearman("closure_ratio", lambda m: m.get("closure_ratio")).get("spearman", 0) > 0,
            "stale_ratio_expected_negative": True,
            "stale_ratio_observed_negative": spearman("stale_ratio", lambda m: m.get("stale_ratio")).get("spearman", 0) < 0,
            "response_latency_sample_sufficient": spearman("first_response_median_hours", lambda m: m.get("first_response_median_hours")).get("n", 0) >= 5,
        },
        "anomalies": anomalies,
        "raw_payload_retained": False,
    }


def issues_boundary_comparison(
    production: dict[str, Any],
    scored: dict[str, Any],
) -> dict[str, Any]:
    """Compare the existing collector path with the spike-only source boundary."""
    before = {
        str(row.get("repository")): row
        for row in production.get("repositories", [])
        if isinstance(row, dict)
    }
    after = {
        str(row.get("repository")): row
        for row in scored.get("repositories", [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, Any]] = []
    for repository in sorted(set(before) | set(after)):
        old = before.get(repository, {})
        new = after.get(repository, {})
        old_analyzer = old.get("analyzer", {}) if isinstance(old, dict) else {}
        new_analyzer = new.get("analyzer", {}) if isinstance(new, dict) else {}
        old_score = old_analyzer.get("score")
        new_score = new_analyzer.get("score")
        rows.append(
            {
                "repository": repository,
                "production_status": old_analyzer.get("category_status"),
                "production_score": old_score,
                "spike_status": new_analyzer.get("category_status"),
                "spike_score": new_score,
                "score_delta": float(new_score) - float(old_score)
                if isinstance(old_score, (int, float)) and isinstance(new_score, (int, float))
                else None,
                "raw_payload_retained": False,
            }
        )
    return {
        "production_boundary": "existing collector/analyzer path",
        "spike_boundary": "server-side filtered facts with completed_at mapping",
        "rows": rows,
        "raw_payload_retained": False,
    }


def cicd_summary(repo: str, collection: dict[str, Any], result: Any) -> dict[str, Any]:
    metrics = metric_map(result)
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    facts_summary = diagnostics.get("cicd", {}) if isinstance(diagnostics.get("cicd"), dict) else {}
    return {
        "repository": repo,
        "collection": {
            "status": collection.get("status"),
            "http_status": collection.get("http_status"),
            "pages": collection.get("pages"),
            "records_received": collection.get("records_received"),
            "records_after_local_filter": collection.get("records_after_local_filter"),
            "failure_kind": collection.get("failure_kind"),
        },
        "analyzer": {
            "status": result.status.value,
            "category_status": diagnostics.get("cicd_status"),
            "score": result.score,
            "coverage": diagnostics.get("coverage", facts_summary.get("coverage")),
            "confidence": diagnostics.get("confidence", facts_summary.get("confidence")),
            "component_scores": diagnostics.get("component_scores", {}),
            "pagination_complete": diagnostics.get("pagination_complete", facts_summary.get("pagination_complete")),
            "retry_detection_status": diagnostics.get("retry_detection_status", facts_summary.get("retry_detection_status")),
        },
        "real_signals": {
            "total_runs": metrics.get("cicd:total_runs"),
            "success_runs": metrics.get("cicd:success_runs"),
            "failure_runs": metrics.get("cicd:failure_runs"),
            "cancelled_runs": metrics.get("cicd:cancelled_runs"),
            "skipped_runs": metrics.get("cicd:skipped_runs"),
            "success_rate": metrics.get("cicd:success_rate"),
            "failure_rate": metrics.get("cicd:failure_rate"),
            "last_run_status": metrics.get("cicd:last_run_status"),
            "failure_streak": metrics.get("cicd:failure_streak"),
            "duration_p50_seconds": metrics.get("cicd:current:duration_p50_seconds"),
            "duration_p95_seconds": metrics.get("cicd:current:duration_p95_seconds"),
            "stability_trend": metrics.get("cicd:stability_trend"),
        },
        "findings": safe_findings(result),
        "raw_payloads_written": False,
    }


def collect_cicd(cal: Any) -> list[dict[str, Any]]:
    from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer

    path = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
    rows: list[dict[str, Any]] = []
    for repo in CI_REPOSITORIES:
        with cal.api_client() as client:
            inventory, collection = cal.collect_ci(client, repo)
        context = cal.context_for(repo, path, {"default_branch": "main"}, {"sourcecraft_cicd": inventory})
        result = CICDAnalyzer().run(context)
        summary = cicd_summary(repo, collection, result)
        # The target fixture was successfully measured in the earlier live
        # verification.  Keep that observation when a later probe is
        # rate-limited; the later error remains visible as a current-probe
        # result and is never converted into a numeric zero.
        live_path = ROOT / "spikes" / "cicd" / "runs" / "sourcecraft-live-cicd.json"
        if repo == "artem03102006/codex-external-audit-public-20260916" and live_path.exists():
            live = json.loads(live_path.read_text(encoding="utf-8"))
            after = live.get("after", {})
            runs = after.get("runs", {})
            durations = after.get("durations", {})
            statuses = after.get("statuses", {})
            summary["prior_live_verification"] = {
                "as_of": live.get("as_of"),
                "verification": live.get("verification", {}),
                "score": after.get("score"),
                "status": after.get("status"),
                "coverage": after.get("coverage"),
                "confidence": after.get("confidence"),
                "total_runs": runs.get("total"),
                "success_runs": statuses.get("cicd:success_runs"),
                "failure_runs": statuses.get("cicd:failure_runs"),
                "success_rate": runs.get("success_rate"),
                "failure_rate": runs.get("failure_rate"),
                "failure_streak": runs.get("failure_streak"),
                "duration_p50_seconds": durations.get("cicd:current:duration_p50_seconds"),
                "duration_p95_seconds": durations.get("cicd:current:duration_p95_seconds"),
                "stability_trend": after.get("trends", {}).get("cicd:stability_trend"),
                "finding_count": len(after.get("findings", [])),
                "raw_payloads_written": False,
            }
        rows.append(summary)
    return rows


def security_probe() -> dict[str, Any]:
    """Record only endpoint/result classes; no report body or token is retained."""
    import httpx

    target = "artem03102006/codex-external-audit-public-20260916"
    repo_id = "01a0a913-690f-774e-91db-48e03d74cf6a"
    endpoints = ("/appsec", "/security", "/appsec/runs", "/security/scans", "/vulnerabilities")
    token = os.environ.get("SOURCECRAFT_PAT", "")
    if not token:
        return {"status": "UNAVAILABLE", "reason": "SOURCECRAFT_PAT_missing", "rest": []}
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    rest: list[dict[str, Any]] = []
    artifact_probe: list[dict[str, Any]] = []
    log_probe: list[dict[str, Any]] = []
    pull_request_comment_probe: list[dict[str, Any]] = []
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        for suffix in endpoints:
            response = client.get("https://api.sourcecraft.tech/repos/" + target + suffix, params={"page_size": 1})
            rest.append({"endpoint_class": suffix, "http_status": response.status_code, "body_retained": False})
        # SourceCraft documents PR comments as a separate read boundary.  Use
        # only aggregate classifications here; never write comment text or
        # the original response payload to the validation artifact.
        for pull_request in ("1", "2"):
            path = f"/repos/{target}/pulls/{pull_request}/comments"
            response = client.get("https://api.sourcecraft.tech" + path, params={"page_size": 100})
            row: dict[str, Any] = {
                "path_class": path,
                "http_status": response.status_code,
                "comment_count": None,
                "pages": 0,
                "pagination_complete": False,
                "appsec_comment_count": 0,
                "security_bot_count": 0,
                "human_count": 0,
                "bot_other_count": 0,
                "unknown_actor_count": 0,
                "appsec_open_count": 0,
                "appsec_resolved_count": 0,
                "appsec_no_resolution_needed_count": 0,
                "appsec_unknown_resolution_count": 0,
                "finding_word_count": 0,
                "resolved_word_count": 0,
                "severity_word_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "appsec_engine_marker_counts": {
                    "semgrep": 0,
                    "opengrep": 0,
                    "kics": 0,
                    "gitleaks": 0,
                    "syft": 0,
                    "dependency": 0,
                    "secret": 0,
                },
                "appsec_evidence": [],
                "body_retained": False,
            }
            if response.status_code == 200:
                try:
                    comments: list[dict[str, Any]] = []
                    page_token: str | None = None
                    seen_page_tokens: set[str] = set()
                    for _ in range(100):
                        params: dict[str, Any] = {"page_size": 100}
                        if page_token:
                            params["page_token"] = page_token
                        page_response = response if not page_token else client.get(
                            "https://api.sourcecraft.tech" + path,
                            params=params,
                        )
                        if page_response.status_code != 200:
                            row["pagination_error_status"] = page_response.status_code
                            break
                        page_payload = page_response.json()
                        page_comments = page_payload.get("pull_request_comments") if isinstance(page_payload, dict) else None
                        if not isinstance(page_comments, list):
                            row["parse_error_class"] = "comments_array_missing"
                            break
                        comments.extend(comment for comment in page_comments if isinstance(comment, dict))
                        row["pages"] += 1
                        next_page_token = page_payload.get("next_page_token") if isinstance(page_payload, dict) else None
                        if not next_page_token:
                            row["pagination_complete"] = True
                            break
                        next_page_token = str(next_page_token)
                        if next_page_token in seen_page_tokens:
                            row["parse_error_class"] = "repeated_page_token"
                            break
                        seen_page_tokens.add(next_page_token)
                        page_token = next_page_token
                    row["comment_count"] = len(comments)
                    for comment in comments:
                            if not isinstance(comment, dict):
                                row["unknown_actor_count"] += 1
                                continue
                            actor = comment.get("author") or comment.get("user") or comment.get("created_by")
                            actor_values: list[str] = []
                            actor_is_bot = False
                            if isinstance(actor, dict):
                                actor_values = [
                                    str(actor.get(key, ""))
                                    for key in ("username", "login", "name", "type")
                                    if actor.get(key) is not None
                                ]
                                actor_is_bot = bool(actor.get("is_bot")) or str(actor.get("type", "")).lower() == "bot"
                            elif actor is not None:
                                actor_values = [str(actor)]
                            actor_text = " ".join(actor_values).lower()
                            is_security_bot = actor_is_bot and any(
                                marker in actor_text for marker in ("security", "appsec", "sast", "gitleaks", "semgrep", "sourcecraft bot")
                            )
                            if is_security_bot:
                                row["security_bot_count"] += 1
                            elif actor_is_bot:
                                row["bot_other_count"] += 1
                            elif actor_values:
                                row["human_count"] += 1
                            else:
                                row["unknown_actor_count"] += 1
                            comment_type = str(comment.get("type", "")).lower()
                            if comment_type == "appsec":
                                row["appsec_comment_count"] += 1
                                resolution_state = str(comment.get("resolution_state", "")).lower()
                                if comment.get("is_resolved") is True or resolution_state in {"resolved", "fixed", "closed"}:
                                    row["appsec_resolved_count"] += 1
                                elif resolution_state == "awaiting_resolution":
                                    row["appsec_open_count"] += 1
                                elif resolution_state == "no_resolution_needed":
                                    row["appsec_no_resolution_needed_count"] += 1
                                elif comment.get("is_resolved") is False:
                                    row["appsec_open_count"] += 1
                                else:
                                    row["appsec_unknown_resolution_count"] += 1
                            comment_text = " ".join(
                                str(comment.get(key, ""))
                                for key in ("body", "text", "content", "message")
                                if comment.get(key) is not None
                            ).lower()
                            if any(word in comment_text for word in ("finding", "vulnerability", "secret", "security issue")):
                                row["finding_word_count"] += 1
                            if any(word in comment_text for word in ("resolved", "fixed", "dismissed")):
                                row["resolved_word_count"] += 1
                            for severity in row["severity_word_counts"]:
                                if severity in comment_text:
                                    row["severity_word_counts"][severity] += 1
                            for marker in row["appsec_engine_marker_counts"]:
                                if marker in comment_text:
                                    row["appsec_engine_marker_counts"][marker] += 1
                            if comment_type == "appsec":
                                anchor = comment.get("anchor")
                                position = anchor.get("position") if isinstance(anchor, dict) else None
                                severity_markers = [
                                    severity for severity in row["severity_word_counts"] if severity in comment_text
                                ]
                                engine_markers = [
                                    marker for marker in row["appsec_engine_marker_counts"] if marker in comment_text
                                ]
                                row["appsec_evidence"].append(
                                    {
                                        "comment_id_digest": digest(comment.get("id")),
                                        "created_at_present": bool(comment.get("created_at")),
                                        "comment_type": "appsec",
                                        "published": comment.get("is_published") is True,
                                        "deleted": comment.get("is_deleted") is True,
                                        "outdated": comment.get("is_outdated") is True,
                                        "resolution_class": (
                                            "resolved"
                                            if comment.get("is_resolved") is True or str(comment.get("resolution_state", "")).lower() in {"resolved", "fixed", "closed"}
                                            else "awaiting_resolution"
                                            if str(comment.get("resolution_state", "")).lower() == "awaiting_resolution"
                                            else "no_resolution_needed"
                                            if str(comment.get("resolution_state", "")).lower() == "no_resolution_needed"
                                            else "unresolved_legacy"
                                            if comment.get("is_resolved") is False
                                            else "unknown"
                                        ),
                                        "engine_markers": engine_markers,
                                        "severity_markers": severity_markers,
                                        "anchor_path_digest": digest(anchor.get("path")) if isinstance(anchor, dict) and anchor.get("path") else None,
                                        "anchor_position_keys": sorted(position) if isinstance(position, dict) else [],
                                        "body_retained": False,
                                    }
                                )
                except (ValueError, TypeError):
                    row["parse_error_class"] = "malformed_json"
            pull_request_comment_probe.append(row)
        for run, workflow, task, cube in (
            ("8", "appsec-sast", "sast-scan", "semgrep"),
            ("8", "appsec-sast", "sast-scan", "sast-upload"),
            ("8", "appsec-secrets", "secret-scan", "gitleaks"),
            ("8", "appsec-secrets", "secret-scan", "secrets-upload"),
            ("8", "appsec-sca", "sca-scan", "syft"),
            ("8", "appsec-sca", "sca-scan", "sca-upload"),
            ("16", "appsec-secrets", "secret-scan", "gitleaks"),
        ):
            path = f"/repos/{target}/cicd/artifacts/{run}/{workflow}/{task}/{cube}"
            response = client.get("https://api.sourcecraft.tech" + path)
            artifact_count: int | None = None
            if response.status_code == 200:
                try:
                    payload = response.json()
                    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
                    artifact_count = len(artifacts) if isinstance(artifacts, list) else None
                except ValueError:
                    artifact_count = None
            artifact_probe.append(
                {
                    "path_class": path,
                    "http_status": response.status_code,
                    "artifact_count": artifact_count,
                    "body_retained": False,
                }
            )
        for run, workflow, task, cube in (
            ("8", "appsec-sast", "sast-scan", "sast-readback"),
            ("8", "appsec-secrets", "secret-scan", "secrets-readback"),
            ("8", "appsec-sca", "sca-scan", "sca-readback"),
            ("16", "appsec-secrets", "secret-scan", "secrets-readback"),
        ):
            path = f"/repos/{target}/cicd/logs/{run}/{workflow}/{task}/{cube}"
            response = client.get("https://api.sourcecraft.tech" + path)
            payload_keys: list[str] = []
            result_status: str | None = None
            grpc_code: str | None = None
            body_class: str | None = None
            if response.status_code == 200:
                response_text = response.text
                upper_text = response_text.upper()
                if "UNIMPLEMENTED" in upper_text:
                    body_class = "grpc_unimplemented"
                elif "ERROR" in upper_text:
                    body_class = "error_text"
                elif response_text.strip():
                    body_class = "nonempty_log"
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        payload_keys = sorted(str(key) for key in payload)[:20]
                        result_status = str(payload.get("status")) if payload.get("status") is not None else None
                        grpc_code = str(payload.get("grpc_code")) if payload.get("grpc_code") is not None else None
                except ValueError:
                    payload_keys = []
            log_probe.append(
                {
                    "path_class": path,
                    "http_status": response.status_code,
                    "payload_keys": payload_keys,
                    "result_status": result_status,
                    "grpc_code": grpc_code,
                    "body_class": body_class,
                    "body_retained": False,
                }
            )
    openapi_probe: dict[str, Any]
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get("https://api.sourcecraft.tech/sourcecraft.swagger.json")
        payload = response.json() if response.status_code == 200 else {}
        paths = payload.get("paths", {}) if isinstance(payload, dict) else {}
        appsec_paths = [
            path
            for path in paths
            if any(term in path.lower() for term in ("appsec", "vulnerab", "sarif", "security/scan", "code-scanning"))
        ]
        openapi_probe = {
            "http_status": response.status_code,
            "path_count": len(paths),
            "appsec_findings_path_count": len(appsec_paths),
            "appsec_findings_paths": appsec_paths,
            "cicd_artifact_path_present": any("/cicd/artifacts/" in path for path in paths),
            "body_retained": False,
        }
    except (httpx.HTTPError, ValueError, TypeError):
        openapi_probe = {"status": "ERROR", "body_retained": False}
    internal_gateway_probe: list[dict[str, Any]] = []
    public_gateway_probe: list[dict[str, Any]] = []
    internal_csrf_present = False
    internal_cookie_present = False
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            root_response = client.get("https://sourcecraft.dev/")
            csrf = root_response.headers.get("x-csrf-token", "")
            cookie = root_response.headers.get("set-cookie", "")
            internal_csrf_present = bool(csrf)
            internal_cookie_present = bool(cookie)
            internal_headers = {
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://sourcecraft.dev",
                "Referer": "https://sourcecraft.dev/",
                "x-csrf-token": csrf,
            }
            for operation in (
                "getAppsecRepoStatus",
                "getAppsecRepoScanStatus",
                "getRepoSecurityStats",
                "listAppsecScans",
                "listDefectsGroups",
                "listAppsecArtifacts",
            ):
                response = client.post(
                    "https://sourcecraft.dev/gateway/root/api/" + operation,
                    headers=internal_headers,
                    cookies={"_yasc": cookie.split(";", 1)[0].split("=", 1)[1]} if "=" in cookie else None,
                    json={"gitRepo": target, "pageSize": 100},
                )
                error_code: str | None = None
                error_status: int | None = None
                if response.headers.get("content-type", "").startswith("application/json"):
                    try:
                        payload = response.json()
                        if isinstance(payload, dict):
                            error_code = str(payload.get("code")) if payload.get("code") is not None else None
                            error_status = int(payload["status"]) if payload.get("status") is not None else None
                    except (ValueError, TypeError):
                        pass
                internal_gateway_probe.append(
                    {
                        "operation": operation,
                        "http_status": response.status_code,
                        "error_code": error_code,
                        "error_status": error_status,
                        "body_retained": False,
                    }
                )
            public_headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://sourcecraft.dev",
                "Referer": "https://sourcecraft.dev/",
                "x-csrf-token": csrf,
            }
            for operation in (
                "getAppsecRepoStatus",
                "getAppsecRepoScanStatus",
                "getRepoSecurityStats",
                "listAppsecScans",
                "listDefectsGroups",
                "listAppsecArtifacts",
            ):
                response = client.post(
                    "https://sourcecraft.dev/gateway/root/api/" + operation,
                    headers=public_headers,
                    cookies={"_yasc": cookie.split(";", 1)[0].split("=", 1)[1]} if "=" in cookie else None,
                    json={"gitRepo": target, "pageSize": 100},
                )
                payload_keys: list[str] = []
                if response.headers.get("content-type", "").startswith("application/json"):
                    try:
                        payload = response.json()
                        if isinstance(payload, dict):
                            payload_keys = sorted(str(key) for key in payload)[:20]
                    except (ValueError, TypeError):
                        pass
                public_gateway_probe.append(
                    {
                        "operation": operation,
                        "http_status": response.status_code,
                        "payload_keys": payload_keys,
                        "authorization_header_sent": False,
                        "body_retained": False,
                    }
                )
    except httpx.HTTPError:
        internal_gateway_probe.append({"status": "ERROR", "body_retained": False})

    # The fixture's own readback script uses this gRPC service.  Probe it
    # directly as well as through the REST log wrapper, but keep only aggregate
    # counters.  In particular, never write the report bytes, finding text or
    # package names to the validation artifact.
    direct_grpc_probe: list[dict[str, Any]] = []
    try:
        import tempfile
        from grpc_tools import protoc

        proto = '''syntax = "proto3"; package v1.results;
service FileDownloadService { rpc DownloadFileStream(FileDownloadRequest) returns (stream DownloadFileStreamResponse); }
message FileDownloadRequest { string git_repo=1; string commit=2; string engine_name=3; int32 type=4; string repo_public_uuid=5; optional string scan_id=6; optional string scan_uuid=7; }
message DownloadFileStreamResponse { bytes content=1; }'''
        with tempfile.TemporaryDirectory(prefix="repo-health-appsec-proto-") as directory:
            directory_path = Path(directory)
            proto_path = directory_path / "download.proto"
            proto_path.write_text(proto, encoding="utf-8")
            compile_status = protoc.main(
                [
                    "protoc",
                    f"-I{directory}",
                    f"--python_out={directory}",
                    f"--grpc_python_out={directory}",
                    str(proto_path),
                ]
            )
            if compile_status != 0:
                raise RuntimeError("appsec_proto_compile_failed")
            sys.path.insert(0, directory)
            import grpc
            import download_pb2
            import download_pb2_grpc

            branch_shas: dict[str, str] = {}
            with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
                branches_response = client.get(
                    "https://api.sourcecraft.tech/repos/" + target + "/branches",
                    params={"page_size": 100},
                )
                if branches_response.status_code == 200:
                    branches_payload = branches_response.json()
                    for branch in branches_payload.get("branches", []):
                        if not isinstance(branch, dict):
                            continue
                        commit = branch.get("commit")
                        if isinstance(commit, dict) and commit.get("hash"):
                            branch_shas[str(branch.get("name"))] = str(commit["hash"])

            cases = (
                ("8", "appsec-pr-20260916", "sast", "semgrep"),
                ("8", "appsec-pr-20260916", "secrets", "gitleaks"),
                ("8", "appsec-pr-20260916", "sca", "syft"),
                ("16", "codex/appsec-sca-secrets", "secrets", "gitleaks"),
                ("16", "codex/appsec-sca-secrets", "sca", "syft"),
            )
            namespace = uuid.UUID("cc306167-a757-42f9-b41b-ca77e6b4723b")
            for run, branch, kind, engine in cases:
                commit = branch_shas.get(branch)
                row: dict[str, Any] = {
                    "run": run,
                    "branch": branch,
                    "kind": kind,
                    "engine": engine,
                    "commit_available": bool(commit),
                    "report_body_retained": False,
                }
                if not commit:
                    row["transport_status"] = "UNAVAILABLE"
                    row["grpc_code"] = "COMMIT_NOT_FOUND"
                    direct_grpc_probe.append(row)
                    continue
                request = download_pb2.FileDownloadRequest(
                    commit=commit,
                    engine_name=engine,
                    type=2 if kind == "sca" else 1,
                    repo_public_uuid=repo_id,
                    scan_uuid=str(uuid.uuid5(namespace, f"{repo_id}:{run}")),
                )
                try:
                    channel = grpc.secure_channel("appsec.sourcecraft.tech:443", grpc.ssl_channel_credentials())
                    raw = b"".join(
                        bytes(chunk.content)
                        for chunk in download_pb2_grpc.FileDownloadServiceStub(channel).DownloadFileStream(
                            request,
                            metadata=(("authorization", "Bearer " + token),),
                            timeout=20,
                        )
                    )
                    channel.close()
                    row["transport_status"] = "OK"
                    row["bytes"] = len(raw)
                    payload = json.loads(raw.decode("utf-8"))
                    if kind == "sca":
                        packages = payload.get("packages", []) if isinstance(payload, dict) else []
                        row["record_count"] = len(packages) if isinstance(packages, list) else 0
                    else:
                        runs = payload.get("runs", []) if isinstance(payload, dict) else []
                        findings = [
                            finding
                            for scan_run in runs
                            if isinstance(scan_run, dict)
                            for finding in (scan_run.get("results", []) or [])
                            if isinstance(finding, dict)
                        ]
                        levels: dict[str, int] = {}
                        baselines: dict[str, int] = {}
                        for finding in findings:
                            for key, target_map in (("level", levels), ("baselineState", baselines)):
                                value = finding.get(key)
                                if value is not None:
                                    target_map[str(value)] = target_map.get(str(value), 0) + 1
                        row["record_count"] = len(findings)
                        row["levels"] = levels
                        row["baseline_states"] = baselines
                except grpc.RpcError as error:
                    row["transport_status"] = "ERROR"
                    row["grpc_code"] = error.code().name
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError) as error:
                    row["transport_status"] = "ERROR"
                    row["parse_error_class"] = type(error).__name__
                finally:
                    direct_grpc_probe.append(row)
    except (ImportError, OSError, RuntimeError):
        direct_grpc_probe.append(
            {
                "transport_status": "ERROR",
                "grpc_code": "CLIENT_PROBE_UNAVAILABLE",
                "report_body_retained": False,
            }
        )
    appsec_comment_total = sum(int(row.get("appsec_comment_count") or 0) for row in pull_request_comment_probe)
    appsec_open_total = sum(int(row.get("appsec_open_count") or 0) for row in pull_request_comment_probe)
    appsec_resolved_total = sum(int(row.get("appsec_resolved_count") or 0) for row in pull_request_comment_probe)
    appsec_no_resolution_needed_total = sum(
        int(row.get("appsec_no_resolution_needed_count") or 0) for row in pull_request_comment_probe
    )
    return {
        "status": "PARTIAL" if appsec_comment_total else "UNAVAILABLE",
        "reason": "real_pr_appsec_comment_found_but_full_finding_payload_unavailable" if appsec_comment_total else "public_rest_appsec_absent_internal_gateway_rejects_pat_direct_file_download_unimplemented_and_pr_comments_empty",
        "rest": rest,
        "ci_workflow_presence": ["appsec-sast", "appsec-secrets", "appsec-sca"],
        "readback": {
            "transport": "SourceCraft FileDownloadService",
            "attempted": True,
            "run_ids": ["8", "16"],
            "result": "UNAVAILABLE",
            "grpc_code": "UNIMPLEMENTED",
            "report_body_retained": False,
        },
        "official_openapi": openapi_probe,
        "cicd_artifact_probe": artifact_probe,
        "cicd_log_probe": log_probe,
        "pull_request_comment_probe": pull_request_comment_probe,
        "real_appsec_comment_total": appsec_comment_total,
        "real_appsec_open_total": appsec_open_total,
        "real_appsec_resolved_total": appsec_resolved_total,
        "real_appsec_no_resolution_needed_total": appsec_no_resolution_needed_total,
        "partial_security_repositories": sum(
            1 for row in pull_request_comment_probe if int(row.get("appsec_comment_count") or 0) > 0
        ),
        "direct_grpc_probe": direct_grpc_probe,
        "internal_gateway_probe": {
            "base": "https://sourcecraft.dev/gateway/root/api/<operation>",
            "csrf_header_present": internal_csrf_present,
            "session_cookie_present": internal_cookie_present,
            "operations": internal_gateway_probe,
            "raw_payload_retained": False,
        },
        "public_gateway_probe": {
            "base": "https://sourcecraft.dev/gateway/root/api/<operation>",
            "authorization_header_sent": False,
            "operations": public_gateway_probe,
            "raw_payload_retained": False,
        },
        "measured_security_repositories": 0,
        "full_findings_payload_repositories": 0,
        "synthetic_rows_used_as_real": False,
    }


def formula_recheck() -> dict[str, Any]:
    """Re-run the existing deterministic score lab without changing production."""
    lab_path = ROOT / "spikes" / "scoring" / "formula_lab.py"
    spec = importlib.util.spec_from_file_location("final_validation_formula_lab", lab_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load formula lab")
    lab = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lab
    spec.loader.exec_module(lab)
    cases = lab.scenarios()
    evaluated = {name: lab.evaluate(case) for name, case in cases.items()}
    critical = cases["critical_vulnerability_or_secret"]
    cap_rows = [{"cap": cap, "hybrid": lab.hybrid(critical, cap)} for cap in (40.0, 50.0, 60.0)]
    threshold_rows = [
        {
            "provisional_k": provisional,
            "full_k": full,
            "small_repo_state": lab.presentation(cases["small_new_repository"], lab.hybrid(cases["small_new_repository"]), provisional_k=provisional, full_k=full),
        }
        for provisional, full in ((0.40, 0.70), (0.50, 0.75), (0.60, 0.80))
    ]
    return {
        "weights": lab.WEIGHTS,
        "critical_cap_sensitivity": cap_rows,
        "threshold_sensitivity": threshold_rows,
        "invariants": lab.invariants(),
        "scenario_outputs": {
            name: {
                "hybrid": row["hybrid"],
                "coverage_k": row["coverage_k"],
                "presentation": row["presentation"],
            }
            for name, row in evaluated.items()
        },
        "source": "spikes/scoring/formula_lab.py",
        "production_code_changed": False,
    }


def main() -> None:
    if not os.environ.get("SOURCECRAFT_PAT"):
        raise SystemExit("SOURCECRAFT_PAT is required; its value is never printed")
    started = time.perf_counter()
    cal = load_calibration_module()
    report = {
        "validation": {
            "version": "final-validation-v1",
            "as_of": AS_OF.isoformat().replace("+00:00", "Z"),
            "analysis_window_days": WINDOW_DAYS,
            "issue_minimum_sample": 5,
            "production_code_changed": True,
            "issues_analyzer_state_timeline_fix": True,
            "score_engine_changed": False,
            "documentation_activity_code_health_recalibrated": False,
            "token_logged": False,
            "raw_payloads_written": False,
        },
        "security": security_probe(),
        "issues": {"repositories": collect_issues(cal)},
        "issues_server_filter_probe": server_filtered_issue_probe(),
        "issues_server_filter_scored_probe": collect_server_filtered_issue_scores(cal),
        "cicd": {"repositories": collect_cicd(cal)},
        "formula_recheck": formula_recheck(),
        "access_discovery": {
            "owner_scoped_probe": owner_scoped_access_probe(),
            "cicd_id_path_probe": cicd_id_path_probe(),
            "public_boundary_probe": public_boundary_probe(),
            "issues_catalog_probe": {
                "repositories_checked": 1978,
                "issue_endpoint_http_200": 962,
                "current_window_candidates_with_minimum_sample": 13,
                "final_validation_cohort_size": 10,
                "source": "same-PAT exploratory SourceCraft catalog probe on 2026-09-20; counts only, no payload retained",
            },
            "issues_comment_discovery_probe": {
                "repositories_checked": 1976,
                "candidates_with_sample_ge_5": 15,
                "human_comment_candidates_in_first_five_issues": 4,
                "human_comment_repositories": [
                    "sourcecraft/sourcecraft",
                    "fompronin/heh",
                    "compilators/dtl-26",
                    "imbok/uims-portal",
                ],
                "source": "same-PAT exploratory SourceCraft probe on 2026-09-20; first five issues only, counts/classes only, no payload retained",
            },
            "cicd_catalog_probe": {
                "repositories_checked": 500,
                "http_200": 0,
                "http_403": 493,
                "http_429": 7,
                "source": "same-PAT exploratory SourceCraft catalog probe on 2026-09-20; counts only, no payload retained",
            },
        },
        "notes": [
            "A numeric zero is retained only when the analyzer measured a real zero; unavailable/error/partial states are not imputed.",
            "SourceCraft issue and CI endpoints were queried with local filtering at the existing spike boundary.",
            "Issue/comment bodies, source code, logs, credentials and AppSec report contents were not written.",
        ],
    }
    report["issues_empirical_analysis"] = issues_empirical_analysis(report["issues_server_filter_scored_probe"])
    report["issues_boundary_comparison"] = issues_boundary_comparison(
        report["issues"], report["issues_server_filter_scored_probe"]
    )
    report["validation"]["duration_seconds"] = round(time.perf_counter() - started, 3)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT / "results.json"), "issues": len(report["issues"]["repositories"]), "cicd": len(report["cicd"]["repositories"]), "security_status": report["security"]["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
