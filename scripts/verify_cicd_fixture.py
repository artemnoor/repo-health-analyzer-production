"""Verify the CI/CD analyzer against a fixture or SourceCraft ``/cicd/runs``.

The live mode is a verification-only bridge. Production analysis consumes the
canonical inventory supplied by the health edge and never performs HTTP or
reads a PAT. Live collection keeps only fields needed by ``CICDFacts``; it
does not persist logs, secrets, or the raw SourceCraft response.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "cicd" / "all_success.json"
OUTPUT = ROOT / "spikes" / "cicd" / "runs" / "repo-health-cicd.json"
LIVE_OUTPUT = ROOT / "spikes" / "cicd" / "runs" / "sourcecraft-live-cicd.json"
REPOSITORY = "artem03102006/codex-external-audit-public-20260916"
SOURCECRAFT_API_BASE = "https://api.sourcecraft.tech"
SOURCECRAFT_PAT_ENV = "SOURCECRAFT_PAT"
TIMEOUT_SECONDS = 30.0
MAX_PAGES = 1000

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext  # noqa: E402
from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer  # noqa: E402
from repowise.core.analysis.health.integrations.cicd_facts import (  # noqa: E402
    CICD_SCHEMA_VERSION,
    load_cicd_policy,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--inventory", type=Path, help="canonical SourceCraft CI inventory JSON")
    source.add_argument("--live", action="store_true", help="fetch SourceCraft /cicd/runs")
    parser.add_argument("--repo-path", type=Path, default=ROOT)
    parser.add_argument("--as-of", default="2026-09-19T00:00:00Z")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return value if isinstance(value, Sequence) else None


def _text(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _row_timestamp(row: Mapping[str, Any]) -> datetime | None:
    dates = _mapping(row.get("dates")) or {}
    for key in (
        "finished_at",
        "finished",
        "finishedAt",
        "completed_at",
        "completedAt",
        "end_time",
        "updated_at",
        "updated",
        "updatedAt",
        "created_at",
        "created",
        "createdAt",
        "start_time",
    ):
        timestamp = _datetime(row.get(key) or dates.get(key))
        if timestamp is not None:
            return timestamp
    return None


def _redact_run(row: Mapping[str, Any], page: int) -> dict[str, Any]:
    allowed = {
        "id",
        "run_id",
        "uid",
        "run_slug",
        "slug",
        "status",
        "state",
        "result",
        "created_at",
        "created",
        "createdAt",
        "started_at",
        "started",
        "startedAt",
        "start_time",
        "finished_at",
        "finished",
        "finishedAt",
        "completed_at",
        "completedAt",
        "end_time",
        "updated_at",
        "updated",
        "updatedAt",
        "duration_seconds",
        "duration",
        "durationSeconds",
        "workflow_id",
        "workflowId",
        "workflow_name",
        "workflowName",
        "commit_sha",
        "commit",
        "revision",
        "sha",
        "commit_id",
        "branch",
        "ref",
        "source_branch",
        "tag",
        "environment",
        "environment_name",
        "deployment_marker",
        "deployment_id",
        "retry_group_id",
        "retry_group",
        "rerun_group_id",
        "parent_run_id",
        "parent_id",
        "rerun_of",
        "attempt",
        "attempt_number",
        "correlation_id",
        "correlation",
        "retry_id",
        "deep_link",
        "url",
        "web_url",
        "link",
        "task_ids",
        "taskIds",
    }
    result = {key: row[key] for key in allowed if key in row}
    dates = _mapping(row.get("dates")) or {}
    for key in ("created_at", "started_at", "finished_at", "updated_at"):
        if key not in result and dates.get(key) is not None:
            result[key] = dates[key]
    workflow = _mapping(row.get("workflow"))
    if workflow is None:
        workflows = _sequence(row.get("workflows"))
        workflow = next((item for item in (workflows or ()) if _mapping(item) is not None), None)
        workflow = _mapping(workflow)
    if workflow:
        result["workflow"] = {
            key: workflow[key]
            for key in ("id", "workflow_id", "slug", "name", "title")
            if key in workflow
        }
        if "task_ids" not in result and "tasks" in workflow:
            tasks = _sequence(workflow["tasks"])
            result["task_ids"] = [
                item.get("id") or item.get("slug") if isinstance(item, Mapping) else str(item)
                for item in (tasks or ())
            ]
    result["source_page"] = page
    return result


def _extract_page(payload: object) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    rows = _sequence(payload)
    if rows is not None:
        return [item for item in rows if _mapping(item) is not None], {}
    envelope = _mapping(payload) or {}
    for key in ("runs", "items", "results", "records"):
        rows = _sequence(envelope.get(key))
        if rows is not None:
            return [item for item in rows if _mapping(item) is not None], envelope
    nested = _mapping(envelope.get("data"))
    return _extract_page(nested) if nested is not None else [], envelope


def _next_token(metadata: Mapping[str, Any]) -> str | None:
    pagination = _mapping(metadata.get("pagination")) or {}
    for source in (metadata, pagination):
        for key in (
            "next_page_token",
            "nextPageToken",
            "next_token",
            "continuation_token",
            "continuationToken",
        ):
            token = _text(source.get(key))
            if token:
                return token
    return None


def _server_total(metadata: Mapping[str, Any]) -> int | None:
    pagination = _mapping(metadata.get("pagination")) or {}
    for source in (metadata, pagination):
        for key in ("server_total", "total", "total_count", "totalCount", "count"):
            try:
                return int(source[key]) if source.get(key) is not None else None
            except (TypeError, ValueError):
                continue
    return None


def _digest(rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"rows": list(rows), "metadata": dict(metadata)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fix_log(event: str, **fields: object) -> None:
    """Emit bounded diagnostics for the verification-only report projection."""
    payload = {"event": f"[FIX:cicd-live-report] {event}", **fields}
    print(json.dumps(payload, sort_keys=True, default=str), file=sys.stderr)


def _empty_envelope(reason: str, *, error: bool = False) -> dict[str, Any]:
    return {
        "schema_version": CICD_SCHEMA_VERSION,
        "source_kind": "sourcecraft",
        "source_version": "sourcecraft-cicd-api",
        "status": "error" if error else "unavailable",
        "configured": None,
        "configuration_source": "sourcecraft_cicd_api",
        "permission_state": "unknown",
        "runs": [],
        "pagination": {"complete": False, "pages_fetched": 0},
        "local_filter": {"applied": False},
        "diagnostics": {"reason": reason},
    }


def _collect_live(as_of: datetime, page_size: int) -> tuple[dict[str, Any], dict[str, Any]]:
    token = os.environ.get(SOURCECRAFT_PAT_ENV)
    if not token:
        return _empty_envelope("SOURCECRAFT_PAT is not set"), {
            "status": "UNAVAILABLE",
            "failure_kind": "missing_token",
        }
    owner, repo = REPOSITORY.split("/", 1)
    endpoint = f"{SOURCECRAFT_API_BASE}/repos/{owner}/{repo}/cicd/runs"
    rows: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    next_page: str | None = None
    seen_tokens: set[str] = set()
    failure: dict[str, Any] | None = None
    started = time.perf_counter()
    with httpx.Client(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
    ) as client:
        for page in range(1, MAX_PAGES + 1):
            params: dict[str, object] = {"page_size": page_size}
            if next_page:
                params["page_token"] = next_page
            try:
                response = client.get(endpoint, params=params)
            except httpx.HTTPError as exc:
                failure = {"status": "ERROR", "failure_kind": type(exc).__name__}
                break
            if response.status_code >= 400:
                failure = {
                    "status": "UNAVAILABLE" if response.status_code in {401, 403, 404} else "ERROR",
                    "failure_kind": f"http_{response.status_code}",
                }
                break
            try:
                payload = response.json()
            except ValueError:
                failure = {"status": "ERROR", "failure_kind": "malformed_json"}
                break
            page_rows, page_metadata = _extract_page(payload)
            metadata.update(
                {str(key): value for key, value in page_metadata.items() if key != "runs"}
            )
            rows.extend(_redact_run(row, page) for row in page_rows)
            next_page = _next_token(page_metadata)
            if not next_page:
                break
            if next_page in seen_tokens:
                failure = {"status": "PARTIAL", "failure_kind": "repeated_page_token"}
                break
            seen_tokens.add(next_page)
        else:
            failure = {"status": "PARTIAL", "failure_kind": "max_pages_reached"}
    if failure and failure["status"] in {"UNAVAILABLE", "ERROR"}:
        envelope = _empty_envelope(
            str(failure["failure_kind"]),
            error=failure["status"] == "ERROR",
        )
        envelope["source_snapshot_digest"] = _digest((), {"failure_kind": failure["failure_kind"]})
        return envelope, {
            "status": failure["status"],
            "failure_kind": failure["failure_kind"],
            "endpoint": endpoint,
            "pages_fetched": len({row["source_page"] for row in rows}),
            "records_received": len(rows),
            "records_after_local_filter": 0,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    policy = load_cicd_policy(ROOT)
    start = as_of - timedelta(days=policy.analysis_window_days)
    filtered = [
        row
        for row in rows
        if (timestamp := _row_timestamp(row)) is None or start <= timestamp < as_of
    ]
    envelope = {
        "schema_version": CICD_SCHEMA_VERSION,
        "source_kind": "sourcecraft",
        "source_version": "sourcecraft-cicd-api",
        "status": "partial"
        if failure and failure["status"] == "PARTIAL"
        else "error"
        if failure and failure["status"] == "ERROR"
        else "measured",
        "configured": True,
        "configuration_source": "sourcecraft_cicd_api",
        "permission_state": "granted",
        "runs": filtered,
        "pagination": {
            "complete": failure is None,
            "pages_fetched": len({row["source_page"] for row in rows}),
            "server_total": _server_total(metadata),
            "repeated_token": bool(failure and failure["failure_kind"] == "repeated_page_token"),
            "max_pages_reached": bool(failure and failure["failure_kind"] == "max_pages_reached"),
        },
        "local_filter": {
            "applied": True,
            "analysis_start": start.isoformat(),
            "analysis_end": as_of.isoformat(),
        },
        "source_snapshot_digest": _digest(filtered, metadata),
        "capabilities": {
            "retry_relation": "observed_fields_only",
            "deployment_events": "absent",
            "production_environment": "absent",
            "deployment_commits": "absent",
            "incidents": "absent",
            "restore_events": "absent",
        },
    }
    if failure:
        envelope["diagnostics"] = {"failure_kind": failure["failure_kind"]}
    return envelope, {
        "status": failure["status"] if failure else "MEASURED",
        "failure_kind": failure["failure_kind"] if failure else None,
        "endpoint": endpoint,
        "pages_fetched": envelope["pagination"]["pages_fetched"],
        "records_received": len(rows),
        "records_after_local_filter": len(filtered),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _run(envelope: Mapping[str, Any], repo_path: Path, as_of: datetime) -> dict[str, Any]:
    context = AnalyzerContext(
        repo_path=repo_path,
        repo_id=REPOSITORY,
        head_sha="sourcecraft-live-cicd",
        as_of_ts=as_of,
        mode="offline",
        inventory={"sourcecraft_cicd": dict(envelope)},
    )
    try:
        result = CICDAnalyzer().run(context)
    except Exception as exc:
        _fix_log(
            "analyzer_error",
            repository=REPOSITORY,
            error_type=type(exc).__name__,
        )
        raise
    dumped = result.model_dump(mode="json")
    diagnostics = result.diagnostics
    cicd = diagnostics.get("cicd", {}) if isinstance(diagnostics, Mapping) else {}
    values = {
        item["name"]: item.get("value") for item in dumped["metrics"] if isinstance(item, Mapping)
    }
    problem_runs = diagnostics.get("problem_runs", ())
    timeout_count = sum(
        isinstance(item, Mapping) and item.get("failure_kind") in {"timeout", "timed_out"}
        for item in problem_runs
    )
    report = {
        "status": result.status.value,
        "score": result.score,
        "score_dimension": result.score_dimension,
        "coverage": cicd.get("coverage"),
        "confidence": cicd.get("confidence"),
        "source": {
            "version": cicd.get("source_version"),
            "schema_version": cicd.get("source_schema_version"),
            "snapshot_digest": cicd.get("source_snapshot_digest"),
            "raw_records": cicd.get("raw_record_count", cicd.get("records_observed")),
            "deduplicated_records": cicd.get("deduplicated_record_count", cicd.get("total_runs")),
            "records_observed": cicd.get("records_observed"),
            "records_expected": cicd.get("records_expected"),
            "duplicate_record_count": cicd.get("duplicate_record_count"),
            "out_of_window_count": cicd.get("out_of_window_count"),
            "malformed_record_count": cicd.get("malformed_record_count"),
            "unknown_status_count": cicd.get("unknown_status_count"),
            "records_after_local_filter": None,
            "timeout_count": timeout_count,
            "pages_fetched": cicd.get("pages_fetched"),
            "pagination_complete": cicd.get("pagination_complete"),
        },
        "runs": {
            "total": cicd.get("total_runs"),
            "terminal": cicd.get("terminal_runs"),
            "decisive": cicd.get("decisive_runs"),
            "success_rate": values.get("cicd:success_rate"),
            "failure_rate": values.get("cicd:failure_rate"),
            "latest_run": cicd.get("latest_run"),
            "last_successful_run": cicd.get("latest_successful"),
            "last_run_status": values.get("cicd:last_run_status"),
            "last_run_at": values.get("cicd:last_run_at"),
            "last_success_at": values.get("cicd:last_success_at"),
            "failure_streak": values.get(
                "cicd:consecutive_failure_streak",
                cicd.get("consecutive_failure_streak"),
            ),
        },
        "statuses": {
            name: value
            for name, value in values.items()
            if name.startswith("cicd:") and name.endswith("_runs")
        },
        "durations": {name: value for name, value in values.items() if "duration_" in name},
        "trends": {
            name: value for name, value in values.items() if "trend" in name or "delta" in name
        },
        "evidence": [item.get("json_pointer") for item in dumped["evidence"]],
        "findings": [
            {key: item.get(key) for key in ("id", "subject", "severity", "reason")}
            for item in dumped["findings"]
        ],
        "problem_runs": problem_runs,
        "retry_relations": diagnostics.get("retry_relations", ()),
        "limitations": [item.get("reason") for item in dumped["limitations"]],
        "diagnostics": {
            "cicd_status": diagnostics.get("cicd_status"),
            "retry_detection_status": cicd.get("retry_detection_status"),
            "pagination_complete": cicd.get("pagination_complete"),
            "component_scores": diagnostics.get("component_scores"),
        },
    }
    _fix_log(
        "report_projected",
        repository=REPOSITORY,
        status=report["status"],
        raw_records=report["source"]["raw_records"],
        deduplicated_records=report["source"]["deduplicated_records"],
        out_of_window_count=report["source"]["out_of_window_count"],
        timeout_count=timeout_count,
    )
    return report


def main() -> int:
    args = _parse_args()
    as_of = _as_of(args.as_of)
    output = args.output or (LIVE_OUTPUT if args.live else OUTPUT)
    if args.live:
        envelope, verification = _collect_live(as_of, load_cicd_policy(ROOT).page_size)
    else:
        path = args.inventory or FIXTURE
        envelope = json.loads(path.read_text(encoding="utf-8"))
        verification = {"status": "FIXTURE", "path": str(path)}
    after = _run(envelope, args.repo_path.resolve(), as_of)
    after["source"]["records_after_local_filter"] = verification.get("records_after_local_filter")
    report = {
        "repository": REPOSITORY,
        "as_of": as_of.isoformat(),
        "source": "sourcecraft.cicd",
        "verification": verification,
        "baseline": {
            "status": "NOT_PRESENT",
            "score": None,
            "reason": "No pre-CICD analyzer result exists in this checkout.",
        },
        "after": after,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
