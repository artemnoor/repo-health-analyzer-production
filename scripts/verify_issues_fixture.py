"""Verify the Issues analyzer on the SourceCraft inventory boundary.

The normal verification mode consumes an export produced by the existing
collector.  ``--live`` is a verification-only bridge to the already installed
official ``src api`` CLI: it fetches the requested SourceCraft issue and
comment records, strips bodies and other unneeded payload before building the
same inventory contract, and then runs the real Issues analyzer.  No
SourceCraft transport is part of the production analyzer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
OUTPUT = ROOT / "spikes" / "issues" / "runs" / "repo-health-issues.json"
LIVE_OUTPUT = ROOT / "spikes" / "issues" / "runs" / "sourcecraft-live-issues.json"
REPOSITORY = "artem03102006/codex-external-audit-public-20260916"
SOURCECRAFT_API_BASE = "https://api.sourcecraft.tech"
SOURCECRAFT_WEB_BASE = "https://sourcecraft.dev"
SOURCECRAFT_PAT_ENV = "SOURCECRAFT_PAT"
SOURCECRAFT_TOKEN_ENV = "SOURCECRAFT_TOKEN"
SOURCECRAFT_CLI_ENV = "SOURCECRAFT_CLI"
SOURCECRAFT_CLI_TIMEOUT_SECONDS = 60
SOURCECRAFT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext  # noqa: E402
from repowise.core.analysis.health.integrations.chaoss_adapter import (  # noqa: E402
    CHAOSS_ISSUES_PRS_ID,
    ChaossAdapter,
    issues_prs_adapter,
)
from repowise.core.analysis.health.integrations.issues_facts import (  # noqa: E402
    IssueCollectionFacts,
    load_issues_policy,
    normalize_issue_inventory,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", type=Path, default=FIXTURE)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--inventory", type=Path, help="JSON export from the existing SourceCraft collector")
    source.add_argument(
        "--live",
        action="store_true",
        help="collect the requested repository through the installed official SourceCraft CLI",
    )
    parser.add_argument("--as-of", default="2026-09-16T12:01:00Z")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _as_of(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC)


def _hash_text(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _safe_log(event: str, **fields: Any) -> None:
    """Emit bounded structured progress without credentials or payloads."""
    print(json.dumps({"event": event, **fields}, sort_keys=True, default=str), file=sys.stderr)


def _redact_text(value: object, secret: str | None = None, *, limit: int = 400) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:limit]


def _resolve_sourcecraft_cli() -> tuple[Path | None, tuple[str, ...]]:
    candidates: list[str] = []
    configured = os.environ.get(SOURCECRAFT_CLI_ENV)
    if configured:
        candidates.append(configured)
    for name in ("src", "src.exe"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(str(Path(local_app_data) / "Programs" / "src" / "src.exe"))

    attempts: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(Path(candidate).expanduser())
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        path = Path(normalized)
        attempts.append(str(path))
        if path.is_file():
            return path.resolve(), tuple(attempts)
    return None, tuple(attempts)


def _classify_cli_failure(stderr: str, returncode: int | None) -> str:
    lowered = stderr.lower()
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "permission_denied"
    if "403" in lowered or "forbidden" in lowered:
        return "permission_denied"
    if "404" in lowered or "not found" in lowered:
        return "endpoint_or_repository_not_found"
    return "sourcecraft_cli_error"


def _sourcecraft_cli_version(cli: Path) -> str:
    try:
        completed = subprocess.run(
            [str(cli), "--version"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    for line in (completed.stdout or "").splitlines():
        if line.strip().lower().startswith("version:"):
            return _redact_text(line.split(":", 1)[1], limit=80) or "unknown"
    return "unknown"


def _run_sourcecraft_api(
    cli: Path,
    endpoint: str,
    token: str,
    *,
    collection_key: str,
) -> tuple[object | None, dict[str, Any]]:
    """Run one paginated official CLI request without putting the token in argv."""
    command = [str(cli), "-R", REPOSITORY, "api", endpoint, "--paginate"]
    owner, repo = REPOSITORY.split("/", 1)
    resolved_endpoint = endpoint.replace("{owner}", owner).replace("{repo}", repo)
    _safe_log("sourcecraft_api_start", endpoint=endpoint, collection=collection_key, paginate=True)
    started = time.perf_counter()
    child_env = os.environ.copy()
    child_env.pop(SOURCECRAFT_PAT_ENV, None)
    child_env[SOURCECRAFT_TOKEN_ENV] = token
    metadata: dict[str, Any] = {
        "endpoint": f"{SOURCECRAFT_API_BASE}/{resolved_endpoint}",
        "collection_key": collection_key,
        "paginate_requested": True,
        "timeout_seconds": SOURCECRAFT_CLI_TIMEOUT_SECONDS,
        "cli_path": str(cli),
    }
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SOURCECRAFT_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        metadata.update(
            {
                "status": "ERROR",
                "failure_kind": "timeout",
                "duration_ms": duration_ms,
                "returncode": None,
                "stdout_bytes": len(str(exc.stdout or "").encode("utf-8", errors="replace")),
                "stderr_bytes": len(str(exc.stderr or "").encode("utf-8", errors="replace")),
            }
        )
        _safe_log("sourcecraft_api_error", endpoint=endpoint, failure_kind="timeout", duration_ms=duration_ms)
        return None, metadata
    except OSError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        metadata.update(
            {
                "status": "ERROR",
                "failure_kind": "process_start_error",
                "error_type": type(exc).__name__,
                "duration_ms": duration_ms,
                "returncode": None,
            }
        )
        _safe_log("sourcecraft_api_error", endpoint=endpoint, failure_kind="process_start_error", duration_ms=duration_ms)
        return None, metadata

    duration_ms = int((time.perf_counter() - started) * 1000)
    stdout = completed.stdout or ""
    stderr = _redact_text(completed.stderr, token)
    stdout_bytes = len(stdout.encode("utf-8", errors="replace"))
    stderr_bytes = len((completed.stderr or "").encode("utf-8", errors="replace"))
    metadata.update(
        {
            "duration_ms": duration_ms,
            "returncode": completed.returncode,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
        }
    )
    if completed.returncode != 0:
        metadata.update(
            {
                "status": "ERROR",
                "failure_kind": _classify_cli_failure(stderr, completed.returncode),
                "stderr_summary": stderr,
            }
        )
        _safe_log(
            "sourcecraft_api_error",
            endpoint=endpoint,
            failure_kind=metadata["failure_kind"],
            returncode=completed.returncode,
            duration_ms=duration_ms,
        )
        return None, metadata
    if stdout_bytes > SOURCECRAFT_MAX_OUTPUT_BYTES:
        metadata.update(
            {
                "status": "ERROR",
                "failure_kind": "output_limit_exceeded",
                "output_limit_bytes": SOURCECRAFT_MAX_OUTPUT_BYTES,
            }
        )
        _safe_log("sourcecraft_api_error", endpoint=endpoint, failure_kind="output_limit_exceeded")
        return None, metadata
    if not stdout.strip():
        metadata.update({"status": "ERROR", "failure_kind": "empty_response"})
        _safe_log("sourcecraft_api_error", endpoint=endpoint, failure_kind="empty_response")
        return None, metadata
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        metadata.update(
            {
                "status": "ERROR",
                "failure_kind": "malformed_json",
                "json_error": _redact_text(exc.msg),
            }
        )
        _safe_log("sourcecraft_api_error", endpoint=endpoint, failure_kind="malformed_json")
        return None, metadata
    metadata.update({"status": "MEASURED", "payload_type": type(payload).__name__})
    _safe_log("sourcecraft_api_success", endpoint=endpoint, duration_ms=duration_ms, stdout_bytes=stdout_bytes)
    return payload, metadata


def _extract_paginated_rows(payload: object, collection_key: str) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Accept both CLI-flattened rows and one-page API envelopes."""
    pages: list[Mapping[str, Any]] = []
    rows: list[Mapping[str, Any]] = []
    shape = "unknown"
    if isinstance(payload, Mapping):
        if collection_key in payload:
            pages = [payload]
            shape = "envelope"
        elif "id" in payload:
            rows = [payload]
            shape = "single_record"
        else:
            raise ValueError(f"SourceCraft payload has no {collection_key} collection")
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        items = list(payload)
        if items and all(isinstance(item, Mapping) and collection_key in item for item in items):
            pages = [item for item in items if isinstance(item, Mapping)]
            shape = "slurped_envelopes"
        else:
            rows = [item for item in items if isinstance(item, Mapping)]
            shape = "cli_flattened_rows"
    else:
        raise ValueError("SourceCraft payload must be a JSON object or array")

    if pages:
        for page in pages:
            page_rows = page.get(collection_key)
            if not isinstance(page_rows, Sequence) or isinstance(page_rows, (str, bytes, bytearray)):
                raise ValueError(f"SourceCraft {collection_key} is not an array")
            rows.extend(item for item in page_rows if isinstance(item, Mapping))
        next_page_present = any(bool(str(page.get("next_page_token") or "").strip()) for page in pages)
        pagination = {
            "page_count": len(pages),
            "pagination_complete": not next_page_present,
            "next_page_token_logged": False,
            "shape": shape,
        }
    else:
        pagination = {
            "page_count": 1,
            "pagination_complete": True,
            "next_page_token_logged": False,
            "shape": shape,
        }
    return rows, pagination


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _actor_for_inventory(mapping: Mapping[str, Any]) -> object | None:
    actor = _first(mapping, "author", "actor", "user", "creator")
    if isinstance(actor, Mapping):
        allowed = (
            "id",
            "slug",
            "login",
            "username",
            "name",
            "is_bot",
            "bot",
            "actor_type",
            "user_type",
            "account_type",
            "is_human",
        )
        return {key: actor[key] for key in allowed if key in actor}
    if actor not in (None, ""):
        return str(actor)
    return None


def _state_slug(issue: Mapping[str, Any]) -> str:
    status = issue.get("status")
    if isinstance(status, Mapping):
        value = _first(status, "slug", "name", "status_type", "state")
    else:
        value = status or issue.get("state")
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"closed", "resolved", "done"}:
        return "closed"
    if normalized in {"open", "opened", "active"}:
        return "open"
    return "unknown"


def _sourcecraft_issue_row(issue: Mapping[str, Any], index: int) -> tuple[dict[str, Any] | None, str | None]:
    issue_id = str(_first(issue, "id", "slug") or "").strip()
    slug = str(_first(issue, "slug", "id") or "").strip()
    if not issue_id:
        return None, "missing_issue_id"
    row: dict[str, Any] = {
        "id": issue_id,
        "issue_number": slug or None,
        "url": f"{SOURCECRAFT_WEB_BASE}/{REPOSITORY}/issues/{slug}" if slug else None,
        "created_at": _first(issue, "created_at", "created"),
        "updated_at": _first(issue, "updated_at", "updated"),
        "state": _state_slug(issue),
        "source": "sourcecraft",
        "source_version": "sourcecraft-cli",
        "source_ref": f"{SOURCECRAFT_API_BASE}/repos/{REPOSITORY}/issues/{slug or issue_id}",
        "has_comments": True,
        "has_state_events": False,
        "is_pull_request": False,
        "_source_index": index,
    }
    actor = _actor_for_inventory(issue)
    if actor is not None:
        row["author"] = actor
    return row, None


def _sourcecraft_comment_row(
    comment: Mapping[str, Any],
    *,
    issue_id: str,
    endpoint: str,
    index: int,
) -> tuple[dict[str, Any] | None, str | None]:
    occurred_at = _first(comment, "created_at", "timestamp", "date")
    if occurred_at in (None, ""):
        return None, "missing_comment_timestamp"
    comment_id = str(_first(comment, "id", "message_id", "slug") or f"{issue_id}:comment:{index}").strip()
    row: dict[str, Any] = {
        "id": comment_id,
        "issue_id": issue_id,
        "event_type": "commented",
        "created_at": occurred_at,
        "source_ref": f"{SOURCECRAFT_API_BASE}/{endpoint}/{index}",
    }
    actor = _actor_for_inventory(comment)
    if actor is not None:
        row["author"] = actor
    return row, None


def _empty_live_inventory(*, status: str, permission_state: str = "unknown") -> dict[str, Any]:
    return {
        "source_kind": "sourcecraft",
        "source_version": "sourcecraft-cli",
        "status": status,
        "records_available": False,
        "records_expected": None,
        "pagination_complete": False,
        "local_date_filter_applied": False,
        "comments_available": False,
        "state_events_available": False,
        "permission_state": permission_state,
        "issues": [],
        "issue_comments": [],
        "issue_events": [],
    }


def _collect_live_sourcecraft(as_of: datetime, policy: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Collect only the bounded issue metadata needed by the existing adapter."""
    token = os.environ.get(SOURCECRAFT_PAT_ENV, "")
    preflight: dict[str, Any] = {
        "collector": "official SourceCraft CLI boundary",
        "transport": "src api",
        "api_calls": True,
        "api_base": SOURCECRAFT_API_BASE,
        "repository": REPOSITORY,
        "as_of": as_of.isoformat(),
        "analysis_window_days": policy.analysis_window_days,
        "auth": {"env": SOURCECRAFT_PAT_ENV, "provided": bool(token), "token_logged": False},
        "pagination": {"requested": True, "page_size": "cli_default_100", "next_page_token_logged": False},
        "state_events": {
            "available": False,
            "reason": "The SourceCraft issue and comment endpoints expose current state and comments, not a state-transition history endpoint in this run.",
        },
        "redaction": "Bodies, titles, descriptions, labels, actor logins, tokens, and complete API payloads are not retained in the report.",
    }
    if not token:
        preflight.update({"result": "UNAVAILABLE", "failure_kind": "missing_sourcecraft_pat"})
        return _empty_live_inventory(status="UNAVAILABLE"), preflight

    cli, attempts = _resolve_sourcecraft_cli()
    preflight["cli"] = {
        "resolved": cli is not None,
        "path": str(cli) if cli else None,
        "attempts": attempts,
        "paginate": True,
    }
    if cli is None:
        preflight.update({"result": "UNAVAILABLE", "failure_kind": "sourcecraft_cli_missing"})
        return _empty_live_inventory(status="UNAVAILABLE"), preflight
    cli_version = _sourcecraft_cli_version(cli)
    preflight["cli"]["version"] = cli_version
    source_version = f"sourcecraft-cli:{cli_version}"

    issue_endpoint = "repos/{owner}/{repo}/issues"
    issue_payload, issue_call = _run_sourcecraft_api(cli, issue_endpoint, token, collection_key="issues")
    preflight["issues_request"] = issue_call
    if issue_payload is None:
        permission = "denied" if issue_call.get("failure_kind") == "permission_denied" else "unknown"
        preflight.update({"result": "UNAVAILABLE", "failure_kind": issue_call.get("failure_kind")})
        return _empty_live_inventory(status="UNAVAILABLE", permission_state=permission), preflight
    try:
        issue_records, issue_pagination = _extract_paginated_rows(issue_payload, "issues")
    except ValueError as exc:
        preflight.update({"result": "ERROR", "failure_kind": "malformed_source_shape", "shape_error": str(exc)})
        return _empty_live_inventory(status="ERROR", permission_state="granted"), preflight

    issue_rows: list[dict[str, Any]] = []
    malformed_issue_reasons: list[str] = []
    for index, issue in enumerate(issue_records):
        row, reason = _sourcecraft_issue_row(issue, index)
        if row is None:
            malformed_issue_reasons.append(reason or "malformed_issue")
            continue
        row.pop("_source_index", None)
        issue_rows.append(row)

    comment_rows: list[dict[str, Any]] = []
    comment_request_summaries: list[dict[str, Any]] = []
    malformed_comment_reasons: list[str] = []
    comments_complete = True
    for issue_row in issue_rows:
        issue_id = str(issue_row["id"])
        issue_slug = str(issue_row.get("issue_number") or issue_id)
        comment_endpoint = f"repos/{{owner}}/{{repo}}/issues/{issue_slug}/comments"
        comment_payload, comment_call = _run_sourcecraft_api(cli, comment_endpoint, token, collection_key="issue_comments")
        comment_request_summaries.append(
            {
                "issue_id_sha256_16": _hash_text(issue_id),
                "issue_number": issue_slug,
                "request": comment_call,
            }
        )
        if comment_payload is None:
            comments_complete = False
            continue
        try:
            comments, comment_pagination = _extract_paginated_rows(comment_payload, "issue_comments")
        except ValueError as exc:
            comments_complete = False
            malformed_comment_reasons.append("malformed_comment_shape")
            comment_request_summaries[-1]["shape_error"] = str(exc)
            continue
        comment_request_summaries[-1]["pagination"] = comment_pagination
        if not comment_pagination["pagination_complete"]:
            comments_complete = False
        for index, comment in enumerate(comments):
            row, reason = _sourcecraft_comment_row(
                comment,
                issue_id=issue_id,
                endpoint=comment_endpoint,
                index=index,
            )
            if row is None:
                malformed_comment_reasons.append(reason or "malformed_comment")
                continue
            comment_rows.append(row)

    comments_complete = comments_complete and not malformed_comment_reasons
    issue_pagination_complete = bool(issue_pagination["pagination_complete"])
    source_status = "NO_ISSUES" if not issue_rows and issue_pagination_complete else "MEASURED"
    inventory = {
        "source_kind": "sourcecraft",
        "source_version": source_version,
        "status": source_status,
        "records_available": True,
        "records_expected": len(issue_records),
        "pagination_complete": issue_pagination_complete,
        "local_date_filter_applied": False,
        "comments_available": comments_complete,
        "state_events_available": False,
        "permission_state": "granted",
        "issues": issue_rows,
        "issue_comments": comment_rows,
        "issue_events": [],
    }
    preflight.update(
        {
            "result": "MEASURED" if issue_rows else "NO_ISSUES",
            "raw_issue_count": len(issue_records),
            "normalized_issue_row_count": len(issue_rows),
            "raw_comment_count": len(comment_rows),
            "malformed_issue_count": len(malformed_issue_reasons),
            "malformed_issue_reasons": sorted(set(malformed_issue_reasons)),
            "malformed_comment_count": len(malformed_comment_reasons),
            "malformed_comment_reasons": sorted(set(malformed_comment_reasons)),
            "issues_pagination": issue_pagination,
            "comment_requests": comment_request_summaries,
            "comments_complete": comments_complete,
            "local_date_filter_applied": False,
            "source_state_fields": "current_status_only",
        }
    )
    _safe_log(
        "sourcecraft_collection_finished",
        issue_count=len(issue_rows),
        comment_count=len(comment_rows),
        comments_complete=comments_complete,
        pagination_complete=issue_pagination_complete,
    )
    return inventory, preflight


def _facts_payload(facts: IssueCollectionFacts) -> dict[str, Any]:
    return {
        "status": facts.status.value,
        "issue_count": len(facts.issues),
        "issue_ids": [
            {
                "id_sha256_16": _hash_text(issue.issue_id),
                "number": issue.issue_number,
                "url": issue.url,
                "state": issue.state.value,
                "created_at": issue.created_at.isoformat() if issue.created_at else None,
                "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                "event_count": len(issue.events),
                "comment_event_count": sum(event.event_type.value == "commented" for event in issue.events),
                "state_transition_event_count": sum(event.is_state_transition for event in issue.events),
            }
            for issue in facts.issues
        ],
        "summary": facts.summary(),
        "diagnostics": dict(facts.diagnostics),
    }


def _load_inventory(path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if path is None:
        return {}, {"provided": False, "path": None, "shape": "no_export_supplied"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("collector inventory must be a JSON object")
    keys = sorted(str(key) for key in raw)
    granular_keys = sorted(
        key
        for key in keys
        if key in {"issues", "issue_rows", "issue_facts", "issues_facts", "sourcecraft_issues"}
    )
    return raw, {
        "provided": True,
        "path": str(path),
        "shape": "granular_issue_rows" if granular_keys else "aggregate_or_unknown",
        "top_level_keys": keys,
        "granular_issue_keys": granular_keys,
        "contains_comment_rows": any(key in raw for key in ("comments", "messages", "issue_comments", "sourcecraft_issue_comments")),
        "contains_state_event_rows": any(key in raw for key in ("events", "issue_events", "sourcecraft_issue_events")),
    }


def _context(repo_path: Path, inventory: dict[str, Any], as_of: datetime) -> AnalyzerContext:
    head_sha = "unknown-head"
    head_file = repo_path / ".git" / "HEAD"
    if head_file.is_file():
        head_sha = head_file.read_text(encoding="utf-8", errors="replace").strip()[:80] or head_sha
    return AnalyzerContext(
        repo_path=repo_path,
        repo_id=REPOSITORY,
        head_sha=head_sha,
        as_of_ts=as_of,
        mode="offline",
        inventory=inventory,
        capabilities=("chaoss:events", "git", "local_scan"),
    )


def _result_payload(result: Any) -> dict[str, Any]:
    return {
        "analyzer_id": result.analyzer_id,
        "analyzer_version": result.analyzer_version,
        "status": result.status.value,
        "score": result.score,
        "score_dimension": result.score_dimension,
        "metrics": [
            {
                "name": metric.name,
                "value": metric.value,
                "unit": metric.unit,
                "score": metric.score,
                "population": metric.population,
                "denominator": metric.denominator,
            }
            for metric in result.metrics
        ],
        "findings": [
            {
                "id": finding.id,
                "subject": finding.subject,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "reason": finding.reason,
                "evidence_refs": [
                    {"path": ref.path, "json_pointer": ref.json_pointer, "confidence": ref.confidence}
                    for ref in finding.evidence_refs
                ],
            }
            for finding in result.findings
        ],
        "evidence": [
            {
                "source": ref.source,
                "source_commit": ref.source_commit,
                "path": ref.path,
                "json_pointer": ref.json_pointer,
                "confidence": ref.confidence,
                "redaction": ref.redaction,
            }
            for ref in result.evidence
        ],
        "limitations": [
            {"kind": limitation.kind, "reason": limitation.reason, "affected_scope": limitation.affected_scope}
            for limitation in result.limitations
        ],
        "diagnostics": result.diagnostics,
    }


def main() -> None:
    args = _parse_args()
    repo_path = args.repo_path.resolve()
    as_of = _as_of(args.as_of)
    policy = load_issues_policy(ROOT)
    if args.live:
        inventory, preflight = _collect_live_sourcecraft(as_of, policy)
    else:
        inventory, preflight = _load_inventory(args.inventory.resolve() if args.inventory else None)
    context = _context(repo_path, inventory, as_of)
    facts = normalize_issue_inventory(context, policy)

    before = ChaossAdapter().result(context, analyzer_id=CHAOSS_ISSUES_PRS_ID)
    after = issues_prs_adapter(context)
    legacy_names = {metric.name for metric in before.metrics}
    issue_names = {metric.name for metric in after.metrics if metric.name.startswith("issues:")}
    duplicate_names = sorted(legacy_names.intersection(issue_names))
    issues_diag = after.diagnostics.get("issues") if isinstance(after.diagnostics.get("issues"), dict) else {}
    report = {
        "verification": {
            "repository": REPOSITORY,
            "repo_path": str(repo_path),
            "as_of": as_of.isoformat(),
            "analyzer_id": CHAOSS_ISSUES_PRS_ID,
            "policy_revision": policy.policy_revision,
            "policy_digest": policy.digest,
            "methodology": {
                "open_digger_revision": "63e4b89ecd525221be95fe2a48a714ebb3c722ec",
                "chaoss_metrics_revision": "fae1f4dfc533a6f28499bdba3fb1514ccabc2018",
            },
        },
        "source_preflight": {
            "collector": "existing SourceCraft/CollectOSS boundary only" if not args.live else "official SourceCraft CLI boundary",
            "api_calls": bool(args.live),
            **preflight,
            "result": preflight.get(
                "result",
                issues_diag.get("source_summary", {}).get("status", "UNAVAILABLE")
                if isinstance(issues_diag.get("source_summary"), dict)
                else "UNAVAILABLE",
            ),
            "analyzer_facts_status": facts.status.value,
            "normalized_fact_count": len(facts.issues),
        },
        "before": _result_payload(before),
        "after": _result_payload(after),
        "normalized_facts": _facts_payload(facts),
        "comparison": {
            "before_score": before.score,
            "after_score": after.score,
            "score_delta": after.score - before.score if before.score is not None and after.score is not None else None,
            "added_issue_metric_count": len(issue_names),
            "duplicate_metric_names": duplicate_names,
            "double_count_guard": "legacy_aggregate_metrics_and_normalized_issue_metrics_have_disjoint_names",
            "score_contribution": after.diagnostics.get("issues_score"),
            "score_eligible": after.score is not None,
        },
        "evidence_summary": {
            "issue_source_summary": issues_diag.get("source_summary"),
            "metric_statuses": issues_diag.get("metric_statuses"),
            "actual_counts": {
                "sourcecraft_issue_records": preflight.get("raw_issue_count"),
                "normalized_issue_facts": len(facts.issues),
                "sourcecraft_comment_records": preflight.get("raw_comment_count"),
                "normalized_comment_events": facts.diagnostics.get("comment_count", 0),
                "sourcecraft_state_events": preflight.get("state_event_count", 0),
                "normalized_state_transition_events": sum(
                    event.is_state_transition for issue in facts.issues for event in issue.events
                ),
            },
            "redaction": "No comment bodies, actor logins, or complete source payloads are emitted.",
        },
    }
    output = (args.output or (LIVE_OUTPUT if args.live else OUTPUT)).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report["comparison"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
