"""Inventory-only SourceCraft CI/CD adapter.

This adapter deliberately does not perform HTTP, subprocess, CLI, or PAT
operations. The existing health edge supplies a canonical SourceCraft
inventory; this module validates and normalizes it into CICDFacts.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from .cicd_facts import (
    CICD_SCHEMA_VERSION,
    CICDDataStatus,
    CICDFacts,
    CICDPolicy,
    CICDRetryRelation,
    CICDRunFact,
    CICDRunStatus,
    CICDWindowFacts,
    percentile,
    window_bounds,
)
from .contracts import AnalyzerContext

log = structlog.get_logger("cicd.adapter")

CANONICAL_INVENTORY_KEY = "sourcecraft_cicd"
COMPATIBILITY_KEYS = ("cicd_runs", "sourcecraft_cicd_runs")
TERMINAL_STATUSES = frozenset(
    {
        CICDRunStatus.SUCCESS,
        CICDRunStatus.FAILURE,
        CICDRunStatus.CANCELLED,
        CICDRunStatus.SKIPPED,
        CICDRunStatus.REJECTED,
    }
)


class CICDPayloadError(ValueError):
    """Raised when the canonical inventory envelope is malformed."""


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, (str, bytes, bytearray)):
        return None
    return value if isinstance(value, Sequence) else None


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested(row: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    for key in keys:
        value = _mapping(row.get(key))
        if value is not None:
            return value
    return None


def _text(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _bool_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "complete", "granted", "configured"}:
            return True
        if normalized in {"false", "no", "0", "incomplete", "denied", "unconfigured"}:
            return False
    return None


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = _first(value, "seconds", "duration_seconds", "value")
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration < 0:
        return None
    return duration


def _status(value: object) -> tuple[CICDRunStatus, str | None]:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"success", "succeeded", "successful", "passed", "pass", "ok"}:
        return CICDRunStatus.SUCCESS, None
    if raw in {"failed", "failure", "error", "errored", "timed_out", "timeout"}:
        return CICDRunStatus.FAILURE, "timeout" if "timeout" in raw or "timed_out" in raw else None
    if raw in {"cancelled", "canceled", "cancel", "aborted"}:
        return CICDRunStatus.CANCELLED, None
    if raw in {"skipped", "skip"}:
        return CICDRunStatus.SKIPPED, None
    if raw in {"rejected", "reject", "declined"}:
        return CICDRunStatus.REJECTED, None
    if raw in {
        "created",
        "prepared",
        "pending",
        "queued",
        "running",
        "processing",
        "in_progress",
        "awaiting_approval",
        "waiting",
    }:
        return CICDRunStatus.IN_PROGRESS, None
    return CICDRunStatus.UNKNOWN, None


def _canonical_digest(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def _row_identity(row: Mapping[str, Any]) -> str | None:
    return _text(_first(row, "run_id", "id", "uid", "run_slug", "slug"))


def _completion_score(row: Mapping[str, Any]) -> int:
    fields = (
        ("status", "state", "result"),
        ("created_at", "created", "createdAt"),
        ("started_at", "started", "startedAt"),
        ("finished_at", "finished", "finished_at", "completed_at"),
        ("updated_at", "updated", "updatedAt"),
        ("workflow_id", "workflow", "workflowId"),
        ("commit_sha", "commit", "revision", "sha"),
        ("duration_seconds", "duration"),
    )
    return sum(1 for aliases in fields if _first(row, *aliases) not in (None, ""))


def _deduplicate_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], ...], int]:
    winners: dict[str, tuple[int, datetime | None, str, Mapping[str, Any]]] = {}
    duplicate_count = 0
    for row in rows:
        identity = _row_identity(row)
        if identity is None:
            continue
        updated = _datetime(_first(row, "updated_at", "updated", "updatedAt"))
        candidate = (_completion_score(row), updated, _canonical_digest(row), row)
        previous = winners.get(identity)
        if previous is None:
            winners[identity] = candidate
            continue
        duplicate_count += 1
        previous_key = (
            previous[0],
            previous[1] or datetime.min.replace(tzinfo=UTC),
            previous[2],
        )
        candidate_key = (
            candidate[0],
            candidate[1] or datetime.min.replace(tzinfo=UTC),
            candidate[2],
        )
        if candidate_key[:2] > previous_key[:2] or (
            candidate_key[:2] == previous_key[:2] and candidate_key[2] < previous_key[2]
        ):
            winners[identity] = candidate
    return tuple(item[3] for item in sorted(winners.values(), key=lambda item: _row_identity(item[3]) or "")), duplicate_count


def _run_fact(
    row: Mapping[str, Any],
    index: int,
    page: int,
    *,
    max_reasonable_duration_seconds: float | None = None,
) -> tuple[CICDRunFact | None, str | None]:
    run_id = _row_identity(row)
    if run_id is None:
        return None, "missing_identity"
    workflow = _nested(row, "workflow", "pipeline", "workflow_data")
    if workflow is None:
        workflows = _sequence(row.get("workflows"))
        workflow = next(
            (candidate for candidate in (workflows or ()) if _mapping(candidate) is not None),
            None,
        )
        workflow = _mapping(workflow)
    dates = _nested(row, "dates", "timestamps") or {}
    status_value = _first(row, "status", "state", "result", "run_status")
    status, failure_kind = _status(status_value)
    created_at = _datetime(
        _first(row, "created_at", "created", "createdAt")
        or _first(dates, "created_at", "created", "createdAt")
    )
    started_at = _datetime(
        _first(row, "started_at", "started", "startedAt", "start_time")
        or _first(dates, "started_at", "started", "startedAt", "start_time")
    )
    finished_at = _datetime(
        _first(row, "finished_at", "finished", "finishedAt", "completed_at", "completedAt", "end_time")
        or _first(dates, "finished_at", "finished", "finishedAt", "completed_at", "completedAt", "end_time")
    )
    updated_at = _datetime(
        _first(row, "updated_at", "updated", "updatedAt")
        or _first(dates, "updated_at", "updated", "updatedAt")
    )
    explicit_duration = _duration(_first(row, "duration_seconds", "duration", "durationSeconds"))
    derived_duration = False
    duration = explicit_duration
    if (
        duration is not None
        and max_reasonable_duration_seconds is not None
        and duration > max_reasonable_duration_seconds
    ):
        duration = None
    if duration is None and started_at is not None and finished_at is not None:
        candidate = (finished_at - started_at).total_seconds()
        if (
            math.isfinite(candidate)
            and candidate >= 0
            and (
                max_reasonable_duration_seconds is None
                or candidate <= max_reasonable_duration_seconds
            )
        ):
            duration = candidate
            derived_duration = True
    if status is CICDRunStatus.UNKNOWN:
        status_reason = "unknown_status"
    elif status in TERMINAL_STATUSES and finished_at is None:
        status_reason = "terminal_without_finished_at"
    else:
        status_reason = None
    task_values = _first(row, "task_ids", "tasks", "taskIds")
    if task_values is None:
        task_values = _first(workflow or {}, "tasks", "task_ids", "taskIds")
    task_ids: list[str] = []
    sequence = _sequence(task_values)
    if sequence is not None:
        for task in sequence:
            task_mapping = _mapping(task)
            task_ids.append(_text(_first(task_mapping or {}, "id", "task_id", "slug")) or str(task))
    return (
        CICDRunFact(
            run_id=run_id,
            run_slug=_text(_first(row, "run_slug", "slug")),
            workflow_id=_text(_first(row, "workflow_id", "workflowId"))
            or _text(_first(workflow or {}, "id", "workflow_id", "slug")),
            workflow_name=_text(_first(row, "workflow_name", "workflowName"))
            or _text(_first(workflow or {}, "name", "title", "slug")),
            task_ids=tuple(task_ids),
            raw_status=str(status_value or ""),
            status=status,
            failure_kind=failure_kind,
            event_type=_text(_first(row, "event_type", "event", "trigger", "type")),
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
            updated_at=updated_at,
            duration_seconds=duration,
            derived_duration=derived_duration,
            commit_sha=_text(_first(row, "commit_sha", "commit", "revision", "sha", "commit_id")),
            branch=_text(_first(row, "branch", "ref", "source_branch")),
            tag=_text(_first(row, "tag")),
            environment=_text(_first(row, "environment", "environment_name")),
            deployment_marker=_text(_first(row, "deployment_marker", "deployment_id")),
            retry_group_id=_text(_first(row, "retry_group_id", "retry_group", "rerun_group_id")),
            parent_run_id=_text(_first(row, "parent_run_id", "parent_id", "rerun_of")),
            attempt=_int(_first(row, "attempt", "attempt_number")),
            correlation_id=_text(_first(row, "correlation_id", "correlation", "retry_id")),
            deep_link=_text(_first(row, "deep_link", "url", "web_url", "link")),
            source_json_pointer=f"/runs/{index}",
            source_page=page,
        ),
        status_reason,
    )


def _run_timestamp(run: CICDRunFact) -> datetime | None:
    return run.finished_at if run.terminal else (run.updated_at or run.created_at)


def _inside(run: CICDRunFact, start: datetime, end: datetime) -> bool:
    timestamp = _run_timestamp(run)
    return timestamp is None or start <= timestamp < end


def _streak(runs: Sequence[CICDRunFact]) -> int:
    terminal = sorted(
        (run for run in runs if run.terminal and run.finished_at is not None),
        key=lambda run: (run.finished_at, run.run_id),
    )
    streak = 0
    for run in reversed(terminal):
        if run.status is CICDRunStatus.FAILURE:
            streak += 1
        else:
            break
    return streak


def _window(
    name: str,
    start: datetime,
    end: datetime,
    runs: Sequence[CICDRunFact],
    policy: CICDPolicy,
) -> CICDWindowFacts:
    selected = tuple(run for run in runs if _inside(run, start, end))
    counts = {status.value: 0 for status in CICDRunStatus}
    durations: list[float] = []
    for run in selected:
        counts[run.status.value] += 1
        if run.terminal and run.finished_at is not None and run.duration_seconds is not None:
            durations.append(run.duration_seconds)
    terminal_with_timestamp = tuple(
        run for run in selected if run.terminal and run.finished_at is not None
    )
    terminal = len(terminal_with_timestamp)
    decisive = sum(run.decisive for run in terminal_with_timestamp)
    successful = sum(run.status is CICDRunStatus.SUCCESS for run in terminal_with_timestamp)
    failed = sum(run.status is CICDRunStatus.FAILURE for run in terminal_with_timestamp)
    success_rate = successful / decisive if decisive else None
    failure_rate = failed / decisive if decisive else None
    non_decisive = sum(not run.decisive for run in terminal_with_timestamp)
    non_decisive_rate = non_decisive / terminal if terminal else None
    completion = decisive / terminal if terminal else None
    return CICDWindowFacts(
        name=name,
        start=start,
        end=end,
        total_runs=len(selected),
        terminal_runs=terminal,
        decisive_runs=decisive,
        counts=counts,
        durations=tuple(durations),
        p50_seconds=percentile(durations, 0.50),
        p95_seconds=percentile(durations, 0.95),
        success_rate=success_rate,
        failure_rate=failure_rate,
        non_decisive_rate=non_decisive_rate,
        completion_health=completion,
        failure_streak=_streak(selected),
        eligible_for_trend=(
            terminal >= policy.minimum_trend_runs_per_period
            and decisive >= policy.minimum_trend_runs_per_period
        ),
        limitations=(
            ("insufficient_terminal_sample",)
            if terminal < policy.minimum_terminal_runs
            else (),
        ),
    )


def _retry_key(run: CICDRunFact) -> tuple[str, str] | None:
    if run.retry_group_id:
        return "retry_group", run.retry_group_id
    if run.correlation_id:
        return "correlation", run.correlation_id
    if run.parent_run_id:
        return "parent", run.parent_run_id
    return None


def _retry_relations(runs: Sequence[CICDRunFact]) -> tuple[tuple[CICDRetryRelation, ...], str]:
    explicit = [run for run in runs if _retry_key(run) is not None]
    if not explicit:
        return (), "UNAVAILABLE"
    relations: list[CICDRetryRelation] = []
    failures = [run for run in runs if run.status is CICDRunStatus.FAILURE]
    successes = [run for run in runs if run.status is CICDRunStatus.SUCCESS]
    for success in sorted(successes, key=lambda run: (run.finished_at or datetime.max.replace(tzinfo=UTC), run.run_id)):
        success_key = _retry_key(success)
        if success_key is None:
            continue
        for failure in failures:
            failure_key = _retry_key(failure)
            if failure_key != success_key:
                continue
            if failure.run_id == success.run_id:
                continue
            if failure.finished_at is not None and success.finished_at is not None and success.finished_at <= failure.finished_at:
                continue
            if failure.workflow_key and success.workflow_key and failure.workflow_key != success.workflow_key:
                continue
            if failure.commit_sha and success.commit_sha and failure.commit_sha != success.commit_sha:
                continue
            relation_key = f"{success_key[0]}:{success_key[1]}"
            relations.append(
                CICDRetryRelation(
                    failed_run_id=failure.run_id,
                    successful_run_id=success.run_id,
                    relation_key=relation_key,
                    workflow_key=success.workflow_key or None,
                    commit_sha=success.commit_sha,
                )
            )
            break
    unique = {
        (item.failed_run_id, item.successful_run_id): item
        for item in relations
    }
    return tuple(unique.values()), "MEASURED"


def _empty_facts(
    context: AnalyzerContext,
    policy: CICDPolicy,
    status: CICDDataStatus,
    *,
    source_key: str | None = None,
    source_version: str = "unknown",
    configured: bool | None = None,
    configuration_source: str = "unknown",
    permission_state: str = "unknown",
    limitations: tuple[str, ...] = (),
    diagnostics: Mapping[str, Any] | None = None,
) -> CICDFacts:
    as_of = context.as_of_ts.replace(tzinfo=context.as_of_ts.tzinfo or UTC).astimezone(UTC)
    start = as_of - timedelta(days=policy.analysis_window_days)
    return CICDFacts(
        status=status,
        as_of_at=as_of,
        analysis_start=start,
        analysis_end=as_of,
        configured=configured,
        configuration_source=configuration_source,
        source_key=source_key,
        source_version=source_version,
        permission_state=permission_state,
        coverage=0.0,
        confidence=0.0,
        policy_digest=policy.digest,
        policy_revision=policy.policy_revision,
        limitations=limitations,
        diagnostics=diagnostics or {},
    )


class SourceCraftCICDAdapter:
    """Normalize one already-collected SourceCraft CI inventory."""

    def collect(self, context: AnalyzerContext, policy: CICDPolicy | None = None) -> CICDFacts:
        effective_policy = policy or _default_policy()
        started = datetime.now(UTC)
        envelope, source_key = self._select_envelope(context.inventory)
        if envelope is None:
            log.warning(
                "cicd_inventory_missing",
                repo_id=context.repo_id,
                status=CICDDataStatus.UNAVAILABLE.value,
                source_key=CANONICAL_INVENTORY_KEY,
            )
            return _empty_facts(
                context,
                effective_policy,
                CICDDataStatus.UNAVAILABLE,
                limitations=("sourcecraft_cicd_inventory_missing",),
                diagnostics={"reason": "missing_inventory"},
            )
        try:
            facts = self._normalize(context, envelope, source_key, effective_policy)
        except CICDPayloadError as exc:
            log.error(
                "cicd_inventory_invalid",
                repo_id=context.repo_id,
                status=CICDDataStatus.ERROR.value,
                failure_kind="malformed_payload",
                error_type=type(exc).__name__,
            )
            facts = _empty_facts(
                context,
                effective_policy,
                CICDDataStatus.ERROR,
                source_key=source_key,
                limitations=("malformed_sourcecraft_cicd_inventory",),
                diagnostics={"reason": str(exc)},
            )
        elapsed_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        log.info(
            "cicd_inventory_normalized",
            repo_id=context.repo_id,
            source_key=facts.source_key,
            status=facts.status.value,
            records_observed=facts.records_observed,
            run_count=len(facts.runs),
            duplicate_count=facts.duplicate_record_count,
            malformed_count=facts.malformed_record_count,
            pagination_complete=facts.pagination_complete,
            duration_ms=elapsed_ms,
        )
        return facts

    @staticmethod
    def _select_envelope(inventory: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str | None]:
        for key in (CANONICAL_INVENTORY_KEY, *COMPATIBILITY_KEYS):
            value = inventory.get(key)
            mapping = _mapping(value)
            if mapping:
                return mapping, key
            sequence = _sequence(value)
            if sequence is not None:
                return {
                    "schema_version": CICD_SCHEMA_VERSION,
                    "source_kind": "sourcecraft",
                    "status": "measured",
                    "configured": True,
                    "configuration_source": "observed_runs",
                    "runs": sequence,
                    "pagination": {"complete": True, "pages_fetched": 1},
                }, key
        if "runs" in inventory or "cicd" in inventory:
            return inventory, "inventory"
        return None, None

    def _normalize(
        self,
        context: AnalyzerContext,
        envelope: Mapping[str, Any],
        source_key: str | None,
        policy: CICDPolicy,
    ) -> CICDFacts:
        schema_version = str(envelope.get("schema_version") or CICD_SCHEMA_VERSION)
        if schema_version != CICD_SCHEMA_VERSION:
            raise CICDPayloadError(f"unsupported schema_version: {schema_version}")
        status_raw = str(envelope.get("status") or "measured").strip().lower()
        configured = _bool_value(envelope.get("configured"))
        configuration_source = str(envelope.get("configuration_source") or "unknown")
        permission_state = str(envelope.get("permission_state") or "unknown")
        source_version = str(envelope.get("source_version") or "unknown")
        source_snapshot_digest = _text(envelope.get("source_snapshot_digest"))
        collector_identity = _text(envelope.get("collector_identity") or envelope.get("collector"))
        as_of = context.as_of_ts.replace(tzinfo=context.as_of_ts.tzinfo or UTC).astimezone(UTC)
        analysis_start = as_of - timedelta(days=policy.analysis_window_days)
        pagination = _mapping(envelope.get("pagination")) or {}
        if envelope.get("pagination") is not None and pagination is None:
            raise CICDPayloadError("pagination must be an object")
        complete = _bool_value(pagination.get("complete"))
        pages_fetched = _int(pagination.get("pages_fetched")) or 0
        records_expected = _int(pagination.get("server_total") or pagination.get("records_expected"))
        repeated_token = bool(_bool_value(pagination.get("repeated_token")))
        max_pages_reached = bool(_bool_value(pagination.get("max_pages_reached")))
        if repeated_token or max_pages_reached:
            complete = False
        local_filter = _mapping(envelope.get("local_filter")) or {}
        local_filter_applied = _bool_value(local_filter.get("applied"))
        rows_value = envelope.get("runs")
        if rows_value is None:
            if status_raw in {"unavailable", "error"} or configured is False:
                rows: Sequence[object] = ()
            else:
                raise CICDPayloadError("runs field is required")
        else:
            rows = _sequence(rows_value) or ()
            if _sequence(rows_value) is None:
                raise CICDPayloadError("runs must be an array")
        raw_rows = [row for row in rows if _mapping(row) is not None]
        malformed_count = len(rows) - len(raw_rows)
        malformed_count += sum(
            _row_identity(_mapping(row) or {}) is None for row in raw_rows
        )
        deduped, duplicate_count = _deduplicate_rows([_mapping(row) or {} for row in raw_rows])
        facts: list[CICDRunFact] = []
        unknown_status_count = 0
        terminal_without_timestamp = 0
        for index, row in enumerate(deduped):
            fact, reason = _run_fact(
                row,
                index,
                _int(_first(row, "source_page", "page")) or 1,
                max_reasonable_duration_seconds=policy.analysis_window_days * 86400,
            )
            if fact is None:
                malformed_count += 1
                continue
            if reason == "unknown_status":
                unknown_status_count += 1
            if reason == "terminal_without_finished_at":
                terminal_without_timestamp += 1
            facts.append(fact)
        in_window: list[CICDRunFact] = []
        out_of_window = 0
        for run in facts:
            timestamp = _run_timestamp(run)
            if timestamp is not None and not (analysis_start <= timestamp < as_of):
                out_of_window += 1
            else:
                in_window.append(run)
        runs = tuple(in_window)
        bounds = window_bounds(as_of, policy)
        windows = tuple(_window(name, start, end, runs, policy) for name, start, end in bounds)
        latest_observed = max(
            runs,
            key=lambda run: (run.updated_at or run.created_at or datetime.min.replace(tzinfo=UTC), run.run_id),
            default=None,
        )
        terminal = tuple(run for run in runs if run.terminal and run.finished_at is not None)
        latest_terminal = max(terminal, key=lambda run: (run.finished_at, run.run_id), default=None)
        successful = tuple(run for run in terminal if run.status is CICDRunStatus.SUCCESS)
        latest_successful = max(successful, key=lambda run: (run.finished_at, run.run_id), default=None)
        relations, retry_status = _retry_relations(runs)
        capabilities = _mapping(envelope.get("capabilities")) or {}
        if not relations and retry_status == "UNAVAILABLE" and capabilities.get("retry_relation") in {"absent", "unsupported"}:
            retry_status = "NOT_APPLICABLE"
        observed_count = len(rows)
        valid_identity = len(deduped)
        valid_status = sum(run.status is not CICDRunStatus.UNKNOWN for run in facts)
        valid_terminal_timestamp = sum(run.terminal and run.finished_at is not None for run in facts)
        valid_duration = sum(run.duration_seconds is not None and run.terminal for run in facts)
        field_coverage = {
            "identity": valid_identity / observed_count if observed_count else 0.0,
            "status": valid_status / len(facts) if facts else 0.0,
            "terminal_timestamp": valid_terminal_timestamp / sum(run.terminal for run in facts)
            if any(run.terminal for run in facts)
            else 0.0,
            "duration": valid_duration / sum(run.terminal for run in facts)
            if any(run.terminal for run in facts)
            else 0.0,
        }
        pagination_coverage = 1.0 if complete is True else 0.5 if pages_fetched else 0.0
        core_coverage = (
            pagination_coverage
            * field_coverage["identity"]
            * field_coverage["status"]
            * (field_coverage["terminal_timestamp"] if any(run.terminal for run in facts) else 1.0)
        )
        permission_factor = {"granted": 1.0, "partial": 0.7, "unknown": 0.6, "denied": 0.2}.get(
            permission_state,
            0.6,
        )
        sample_confidence = min(1.0, math.sqrt(len(terminal) / policy.preferred_terminal_runs)) if terminal else 0.0
        confidence = max(0.0, min(1.0, permission_factor * core_coverage * (sample_confidence or (1.0 if not facts else 0.0))))
        limitations: list[str] = []
        if complete is not True:
            limitations.append("pagination_incomplete")
        if malformed_count:
            limitations.append("malformed_records_excluded")
        if unknown_status_count:
            limitations.append("unknown_statuses_excluded_from_rates")
        if terminal_without_timestamp:
            limitations.append("terminal_runs_missing_finished_at")
        if local_filter_applied is not True:
            limitations.append("local_date_filter_not_confirmed")
        source_status = {
            "error": CICDDataStatus.ERROR,
            "unavailable": CICDDataStatus.UNAVAILABLE,
        }.get(status_raw)
        if configured is False:
            final_status = CICDDataStatus.CI_NOT_CONFIGURED
        elif source_status is not None:
            final_status = source_status if not facts else CICDDataStatus.PARTIAL
        elif not facts and malformed_count:
            final_status = CICDDataStatus.ERROR
        elif not facts and configured is True and complete is True:
            final_status = CICDDataStatus.NO_RUNS
        elif not facts and configured is None:
            final_status = CICDDataStatus.UNAVAILABLE
            limitations.append("configuration_state_unknown")
        elif complete is not True:
            final_status = CICDDataStatus.PARTIAL
        elif len(terminal) < policy.minimum_terminal_runs:
            final_status = CICDDataStatus.INSUFFICIENT_HISTORY
        else:
            final_status = CICDDataStatus.MEASURED
        diagnostics = {
            "status_raw": status_raw,
            "source_alias_used": source_key,
            "window_days": policy.analysis_window_days,
            "comparison_period_days": policy.current_period_days,
            "terminal_without_timestamp_count": terminal_without_timestamp,
            "duration_sample_count": valid_duration,
            "raw_row_count": len(rows),
            "deduplicated_row_count": len(deduped),
        }
        return CICDFacts(
            status=final_status,
            as_of_at=as_of,
            analysis_start=analysis_start,
            analysis_end=as_of,
            configured=configured,
            configuration_source=configuration_source,
            source_key=source_key,
            source_version=source_version,
            source_schema_version=schema_version,
            source_snapshot_digest=source_snapshot_digest,
            collector_identity=collector_identity,
            permission_state=permission_state,
            runs=runs,
            windows=windows,
            latest_observed=latest_observed,
            latest_terminal=latest_terminal,
            latest_successful=latest_successful,
            consecutive_failure_streak=_streak(runs),
            duplicate_record_count=duplicate_count,
            malformed_record_count=malformed_count,
            unknown_status_count=unknown_status_count,
            out_of_window_count=out_of_window,
            pagination_complete=complete,
            pages_fetched=pages_fetched,
            records_observed=len(rows),
            records_expected=records_expected,
            local_date_filter_applied=local_filter_applied,
            field_coverage=field_coverage,
            coverage=core_coverage,
            confidence=confidence,
            retry_detection_status=retry_status,
            retry_relations=relations,
            dora_capabilities={str(key): str(value) for key, value in capabilities.items()},
            metric_statuses={
                "ci": final_status.value,
                "retry": "MEASURED" if retry_status == "MEASURED" else retry_status,
            },
            policy_digest=policy.digest,
            policy_revision=policy.policy_revision,
            limitations=tuple(dict.fromkeys(limitations)),
            diagnostics=diagnostics,
        )


def _default_policy() -> CICDPolicy:
    try:
        from .cicd_facts import load_cicd_policy

        return load_cicd_policy()
    except (OSError, TypeError, ValueError):
        log.warning("cicd_policy_fallback", failure_kind="policy_load_error")
        return CICDPolicy()


__all__ = [
    "CANONICAL_INVENTORY_KEY",
    "COMPATIBILITY_KEYS",
    "CICDPayloadError",
    "SourceCraftCICDAdapter",
]
