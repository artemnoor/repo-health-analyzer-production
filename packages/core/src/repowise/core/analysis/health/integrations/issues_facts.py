"""Normalized SourceCraft issue and comment facts.

The health edge owns collection.  This module only normalizes already collected
inventory rows into immutable, privacy-safe facts for the Issues analyzer.  It
does not call SourceCraft, CollectOSS, GitHub, GitLab, or any other API.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import structlog

from .contracts import AnalyzerContext
from .process import workspace_root

log = structlog.get_logger("issues.facts")

ISSUES_CONFIG_RELATIVE = Path("config/analyzers/issues.yaml")
ISSUES_POLICY_REVISION = "issues-sourcecraft-policy-v1"
ISSUES_ANALYZER_VERSION = ISSUES_POLICY_REVISION
COLLECTOSS_COMMIT = "339edc520e79dd1728ca19255d94a05a4a107df1"
OPEN_DIGGER_REVISION = "63e4b89ecd525221be95fe2a48a714ebb3c722ec"
CHAOSS_METRICS_REVISION = "fae1f4dfc533a6f28499bdba3fb1514ccabc2018"


class IssueMetricStatus(StrEnum):
    """Per-metric availability, intentionally narrower than AnalyzerStatus."""

    MEASURED = "MEASURED"
    NO_ISSUES = "NO_ISSUES"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class ActorClass(StrEnum):
    HUMAN = "human"
    BOT = "bot"
    UNKNOWN = "unknown"


class IssueEventType(StrEnum):
    OPENED = "opened"
    COMMENTED = "commented"
    CLOSED = "closed"
    REOPENED = "reopened"
    UPDATED = "updated"
    UNKNOWN = "unknown"


class IssueState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IssuesPolicy:
    """Validated repository-owned Issues policy loaded from YAML."""

    policy_revision: str = ISSUES_POLICY_REVISION
    source_commit: str = COLLECTOSS_COMMIT
    analysis_window_days: int = 90
    trend_bucket_days: int = 30
    maturity_window_days: int = 30
    stale_threshold_days: int = 30
    old_backlog_threshold_days: int = 90
    age_buckets_days: tuple[int, ...] = (15, 30, 60, 90)
    stale_activity_event_types: tuple[str, ...] = ("commented", "reopened")
    exclude_issue_author_from_response: bool = True
    unknown_actor_policy: str = "exclude_from_human_response_and_reduce_coverage"
    known_bot_identities: tuple[str, ...] = ()
    bot_patterns: tuple[str, ...] = (
        r"^dependabot(?:\[bot\])?$",
        r"^renovate(?:\[bot\])?$",
    )
    minimum_sample: int = 5
    minimum_coverage: float = 0.80
    partial_component_min_coverage: float = 0.50
    maximum_findings: int = 25
    response_median_target_hours: float = 72.0
    response_median_breach_hours: float = 360.0
    response_p75_target_hours: float = 168.0
    response_p75_breach_hours: float = 720.0
    close_median_target_hours: float = 360.0
    close_median_breach_hours: float = 1440.0
    close_p75_target_hours: float = 720.0
    close_p75_breach_hours: float = 2160.0
    backlog_age_target_hours: float = 720.0
    backlog_age_breach_hours: float = 2160.0
    responsiveness_weight: float = 0.30
    resolution_weight: float = 0.30
    backlog_weight: float = 0.25
    maintenance_weight: float = 0.15
    issues_max_share: float = 0.25
    digest: str = ""

    def __post_init__(self) -> None:
        positive = {
            "analysis_window_days": self.analysis_window_days,
            "trend_bucket_days": self.trend_bucket_days,
            "maturity_window_days": self.maturity_window_days,
            "stale_threshold_days": self.stale_threshold_days,
            "minimum_sample": self.minimum_sample,
            "maximum_findings": self.maximum_findings,
        }
        if any(int(value) <= 0 for value in positive.values()):
            raise ValueError("Issues policy positive integer values must be greater than zero")
        if self.maturity_window_days > self.analysis_window_days:
            raise ValueError("maturity window cannot exceed analysis window")
        if self.trend_bucket_days > self.analysis_window_days:
            raise ValueError("trend bucket cannot exceed analysis window")
        if not 0.0 < float(self.minimum_coverage) <= 1.0:
            raise ValueError("minimum coverage must be in (0, 1]")
        if not 0.0 < float(self.partial_component_min_coverage) <= 1.0:
            raise ValueError("partial component minimum coverage must be in (0, 1]")
        if float(self.partial_component_min_coverage) > float(self.minimum_coverage):
            raise ValueError("partial component coverage cannot exceed minimum coverage")
        if not 0.0 <= float(self.issues_max_share) <= 1.0:
            raise ValueError("issues_max_share must be in [0, 1]")
        for name in (
            "response_median_target_hours",
            "response_median_breach_hours",
            "response_p75_target_hours",
            "response_p75_breach_hours",
            "close_median_target_hours",
            "close_median_breach_hours",
            "close_p75_target_hours",
            "close_p75_breach_hours",
            "backlog_age_target_hours",
            "backlog_age_breach_hours",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        for target_name, breach_name in (
            ("response_median_target_hours", "response_median_breach_hours"),
            ("response_p75_target_hours", "response_p75_breach_hours"),
            ("close_median_target_hours", "close_median_breach_hours"),
            ("close_p75_target_hours", "close_p75_breach_hours"),
            ("backlog_age_target_hours", "backlog_age_breach_hours"),
        ):
            if float(getattr(self, target_name)) >= float(getattr(self, breach_name)):
                raise ValueError(f"{target_name} must be below {breach_name}")
        if sum(
            float(value)
            for value in (
                self.responsiveness_weight,
                self.resolution_weight,
                self.backlog_weight,
                self.maintenance_weight,
            )
        ) <= 0:
            raise ValueError("Issues score weights must have a positive total")
        object.__setattr__(self, "age_buckets_days", tuple(sorted({int(item) for item in self.age_buckets_days if int(item) > 0})))
        object.__setattr__(self, "stale_activity_event_types", tuple(sorted({str(item) for item in self.stale_activity_event_types})))
        object.__setattr__(self, "known_bot_identities", tuple(sorted({str(item).strip().lower() for item in self.known_bot_identities if str(item).strip()})))
        object.__setattr__(self, "bot_patterns", tuple(str(item) for item in self.bot_patterns if str(item)))


@dataclass(frozen=True)
class IssueEventFact:
    event_id: str
    issue_id: str
    event_type: IssueEventType
    occurred_at: datetime
    actor_key: str | None = None
    actor_class: ActorClass = ActorClass.UNKNOWN
    classification_reason: str = "unknown"
    is_state_transition: bool = False
    source_ref: str | None = None
    source_kind: str = "sourcecraft"

    def __post_init__(self) -> None:
        value = self.occurred_at.replace(tzinfo=self.occurred_at.tzinfo or UTC).astimezone(UTC)
        object.__setattr__(self, "occurred_at", value)
        object.__setattr__(self, "event_id", str(self.event_id))
        object.__setattr__(self, "issue_id", str(self.issue_id))


@dataclass(frozen=True)
class IssueFact:
    issue_id: str
    issue_number: str | None = None
    url: str | None = None
    source: str = "sourcecraft"
    source_version: str = "unknown"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    state: IssueState = IssueState.UNKNOWN
    closed_at: datetime | None = None
    author_key: str | None = None
    author_class: ActorClass = ActorClass.UNKNOWN
    events: tuple[IssueEventFact, ...] = ()
    is_pull_request: bool | None = False
    has_comments: bool | None = None
    has_state_events: bool | None = None
    has_actor_metadata: bool | None = None
    field_coverage: Mapping[str, float] = field(default_factory=dict)
    source_ref: str | None = None
    malformed: bool = False

    def __post_init__(self) -> None:
        for name in ("created_at", "updated_at", "closed_at"):
            value = getattr(self, name)
            if isinstance(value, datetime):
                object.__setattr__(self, name, value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC))
        object.__setattr__(self, "events", tuple(sorted(self.events, key=lambda item: (item.occurred_at, item.event_id))))
        object.__setattr__(self, "field_coverage", MappingProxyType({str(key): float(value) for key, value in self.field_coverage.items()}))

@dataclass(frozen=True)
class IssueCollectionFacts:
    status: IssueMetricStatus
    issues: tuple[IssueFact, ...]
    as_of: datetime
    analysis_start: datetime
    analysis_end: datetime
    source_kind: str = "sourcecraft"
    source_key: str | None = None
    records_observed: int = 0
    records_expected: int | None = None
    issue_records_available: bool | None = None
    issue_comment_records_available: bool | None = None
    pagination_complete: bool | None = None
    local_date_filter_applied: bool | None = None
    comments_available: bool | None = None
    state_events_available: bool | None = None
    actor_metadata_coverage: float = 0.0
    permission_state: str = "unknown"
    source_version: str = "unknown"
    malformed_record_count: int = 0
    duplicate_record_count: int = 0
    excluded_pull_request_count: int = 0
    coverage: float = 0.0
    confidence: float = 0.0
    limitations: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        as_of = self.as_of.replace(tzinfo=self.as_of.tzinfo or UTC).astimezone(UTC)
        start = self.analysis_start.replace(tzinfo=self.analysis_start.tzinfo or UTC).astimezone(UTC)
        end = self.analysis_end.replace(tzinfo=self.analysis_end.tzinfo or UTC).astimezone(UTC)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "analysis_start", start)
        object.__setattr__(self, "analysis_end", end)
        object.__setattr__(self, "issues", tuple(sorted(self.issues, key=lambda item: item.issue_id)))
        object.__setattr__(self, "coverage", _bounded(self.coverage))
        object.__setattr__(self, "confidence", _bounded(self.confidence))
        object.__setattr__(self, "actor_metadata_coverage", _bounded(self.actor_metadata_coverage))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "source_kind": self.source_kind,
            "source_key": self.source_key,
            "source_version": self.source_version,
            "records_observed": self.records_observed,
            "records_expected": self.records_expected,
            "issue_count": len(self.issues),
            "excluded_pull_request_count": self.excluded_pull_request_count,
            "pagination_complete": self.pagination_complete,
            "local_date_filter_applied": self.local_date_filter_applied,
            "comments_available": self.comments_available,
            "state_events_available": self.state_events_available,
            "actor_metadata_coverage": self.actor_metadata_coverage,
            "permission_state": self.permission_state,
            "malformed_record_count": self.malformed_record_count,
            "duplicate_record_count": self.duplicate_record_count,
            "coverage": self.coverage,
            "confidence": self.confidence,
            "limitations": self.limitations,
        }


def _bounded(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _as_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _bool_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "complete", "granted"}:
            return True
        if normalized in {"false", "no", "0", "incomplete", "denied"}:
            return False
    return None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if mapping.get(key) not in (None, ""):
            return mapping[key]
    return None


def _mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, (str, bytes, bytearray)):
        return None
    if isinstance(value, Sequence):
        return value
    return None


def _nested_actor(value: object) -> Mapping[str, Any] | str | None:
    if isinstance(value, str):
        return value
    actor = _mapping(value)
    if actor is None:
        return None
    for key in ("actor", "author", "user", "contributor"):
        nested = actor.get(key)
        if isinstance(nested, (Mapping, str)):
            return nested
    return actor


def _actor_identity(actor: object) -> str | None:
    if isinstance(actor, str):
        return actor.strip() or None
    mapping = _mapping(actor)
    if mapping is None:
        return None
    value = _first(mapping, "login", "username", "name", "id", "user_id", "cntrb_id", "gh_user_id")
    return str(value).strip() if value not in (None, "") else None


def classify_actor(actor: object, policy: IssuesPolicy) -> tuple[ActorClass, str, str | None]:
    """Classify an actor before redacting its identity."""
    raw = _nested_actor(actor)
    mapping = _mapping(raw)
    identity = _actor_identity(raw)

    if mapping is not None:
        for key in ("is_bot", "bot", "actor_is_bot", "author_is_bot"):
            explicit = _bool_value(mapping.get(key))
            if explicit is True:
                return ActorClass.BOT, "explicit_marker", identity
            if explicit is False:
                return ActorClass.HUMAN, "explicit_marker", identity
        actor_type = str(_first(mapping, "actor_type", "user_type", "account_type") or "").strip().lower()
        if actor_type == "bot":
            return ActorClass.BOT, "actor_type", identity
        if actor_type == "user":
            return ActorClass.HUMAN, "actor_type", identity
        explicit_human = _bool_value(_first(mapping, "is_human", "actor_is_human"))
        if explicit_human is True:
            return ActorClass.HUMAN, "explicit_human", identity

    normalized = identity.lower() if identity else ""
    if normalized in set(policy.known_bot_identities):
        return ActorClass.BOT, "known_identity", identity
    for pattern in policy.bot_patterns:
        try:
            if normalized and re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
                return ActorClass.BOT, "pattern", identity
        except re.error:
            log.warning("issues_invalid_bot_pattern", pattern_hash=_hash_text(pattern))
    if mapping is not None and normalized:
        return ActorClass.HUMAN, "explicit_human", identity
    return ActorClass.UNKNOWN, "unknown", identity


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:24]


def _actor_key(source_kind: str, identity: str | None) -> str | None:
    if not identity:
        return None
    return _hash_text(f"{source_kind}:{identity.strip().lower()}")


def _event_type(value: object, default: IssueEventType = IssueEventType.UNKNOWN) -> IssueEventType:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "create": IssueEventType.OPENED,
        "created": IssueEventType.OPENED,
        "open": IssueEventType.OPENED,
        "opened": IssueEventType.OPENED,
        "comment": IssueEventType.COMMENTED,
        "commented": IssueEventType.COMMENTED,
        "comment_created": IssueEventType.COMMENTED,
        "message": IssueEventType.COMMENTED,
        "close": IssueEventType.CLOSED,
        "closed": IssueEventType.CLOSED,
        "reopen": IssueEventType.REOPENED,
        "reopened": IssueEventType.REOPENED,
        "updated": IssueEventType.UPDATED,
        "update": IssueEventType.UPDATED,
    }
    return aliases.get(normalized, default)


def _issue_id(row: Mapping[str, Any]) -> str | None:
    value = _first(row, "issue_id", "id", "gh_issue_id", "number", "issue_number", "gh_issue_number")
    return str(value).strip() if value not in (None, "") else None


def _event_id(row: Mapping[str, Any], issue_id: str, index: int, event_type: IssueEventType, occurred_at: datetime) -> str:
    value = _first(row, "event_id", "message_id", "msg_id", "id")
    if value not in (None, ""):
        return str(value)
    raw = json.dumps(
        {
            "issue_id": issue_id,
            "index": index,
            "type": event_type.value,
            "at": occurred_at.isoformat(),
            "actor": _actor_identity(row),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{issue_id}:{_hash_text(raw)}"


def _event_row(
    row: Mapping[str, Any],
    *,
    issue_id: str,
    policy: IssuesPolicy,
    source_kind: str,
    default_type: IssueEventType = IssueEventType.UNKNOWN,
    index: int = 0,
) -> IssueEventFact | None:
    event_type = _event_type(_first(row, "event_type", "action", "type", "kind"), default_type)
    occurred_at = _as_utc(_first(row, "occurred_at", "timestamp", "created_at", "msg_timestamp", "date"))
    if occurred_at is None:
        return None
    actor = _first(row, "actor", "author", "user", "contributor", "actor_id", "cntrb_id", "gh_user_id")
    actor_class, reason, identity = classify_actor(actor, policy)
    explicit_transition = _bool_value(_first(row, "is_state_transition", "state_transition"))
    is_transition = explicit_transition if explicit_transition is not None else event_type in {
        IssueEventType.OPENED,
        IssueEventType.CLOSED,
        IssueEventType.REOPENED,
    }
    return IssueEventFact(
        event_id=_event_id(row, issue_id, index, event_type, occurred_at),
        issue_id=issue_id,
        event_type=event_type,
        occurred_at=occurred_at,
        actor_key=_actor_key(source_kind, identity),
        actor_class=actor_class,
        classification_reason=reason,
        is_state_transition=bool(is_transition),
        source_ref=str(_first(row, "source_ref", "path", "json_pointer") or "") or None,
        source_kind=source_kind,
    )


def _find_sequence(inventory: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[str | None, Sequence[object] | None]:
    for key in keys:
        sequence = _sequence(inventory.get(key))
        if sequence is not None:
            return key, sequence
    nested = inventory.get("sourcecraft")
    if isinstance(nested, Mapping):
        for key in keys:
            sequence = _sequence(nested.get(key))
            if sequence is not None:
                return f"sourcecraft.{key}", sequence
    rows = inventory.get("chaoss_rows")
    if isinstance(rows, Mapping):
        for key in keys:
            sequence = _sequence(rows.get(key))
            if sequence is not None:
                return f"chaoss_rows.{key}", sequence
    return None, None


def _metadata(inventory: Mapping[str, Any], key: str, default: Any = None) -> Any:
    for candidate in (key, f"issue_{key}", f"issues_{key}"):
        if candidate in inventory:
            return inventory[candidate]
    sourcecraft = inventory.get("sourcecraft")
    if isinstance(sourcecraft, Mapping):
        for candidate in (key, f"issue_{key}", f"issues_{key}"):
            if candidate in sourcecraft:
                return sourcecraft[candidate]
    return default


def _raw_issue_events(row: Mapping[str, Any], key: str) -> tuple[tuple[object, IssueEventType], ...]:
    for candidate in (key, "events", "issue_events"):
        sequence = _sequence(row.get(candidate))
        if sequence is not None:
            return tuple((item, IssueEventType.UNKNOWN) for item in sequence)
    for candidate in ("comments", "messages"):
        sequence = _sequence(row.get(candidate))
        if sequence is not None:
            return tuple((item, IssueEventType.COMMENTED) for item in sequence)
    return ()


def _normalize_issue(
    row: Mapping[str, Any],
    *,
    policy: IssuesPolicy,
    source_kind: str,
    source_version: str,
    top_events: Mapping[str, Sequence[object]],
    top_comments: Mapping[str, Sequence[object]],
    index: int,
) -> tuple[IssueFact | None, bool]:
    issue_id = _issue_id(row)
    if issue_id is None:
        return None, True
    pull_request = _bool_value(_first(row, "is_pull_request", "pull_request", "is_pr"))
    if pull_request is None and _first(row, "pull_request_id", "pr_id") not in (None, ""):
        pull_request = True
    if pull_request is True:
        return None, False

    created_at = _as_utc(_first(row, "created_at", "opened_at", "opened_on", "created"))
    updated_at = _as_utc(_first(row, "updated_at", "last_updated_at", "updated"))
    # SourceCraft's documented issue representation uses ``completed_at`` for
    # terminal issues. Preserve the normalized contract's ``closed_at`` name
    # while accepting that source field; otherwise real closed issues are
    # silently reclassified as open and resolution metrics become biased.
    closed_at = _as_utc(_first(row, "closed_at", "closed_on", "resolved_at", "completed_at"))
    raw_state_value = _first(row, "state", "issue_state", "status")
    raw_state_mapping = _mapping(raw_state_value)
    raw_state = str(
        _first(raw_state_mapping, "slug", "name", "status")
        if raw_state_mapping is not None
        else raw_state_value or ""
    ).strip().lower()
    state = IssueState.CLOSED if raw_state in {"closed", "resolved", "done"} else IssueState.OPEN if raw_state in {"open", "opened", "active"} else IssueState.UNKNOWN
    if closed_at is not None:
        state = IssueState.CLOSED
    malformed = created_at is None
    if created_at is not None and closed_at is not None and closed_at < created_at:
        malformed = True

    author_raw = _first(row, "author", "user", "creator", "author_id", "gh_user_id", "cntrb_id")
    author_class, _author_reason, author_identity = classify_actor(author_raw, policy)
    event_rows: list[tuple[object, IssueEventType]] = list(_raw_issue_events(row, "events"))
    event_rows.extend((item, IssueEventType.UNKNOWN) for item in top_events.get(issue_id, ()))
    event_rows.extend((item, IssueEventType.COMMENTED) for item in top_comments.get(issue_id, ()))
    event_facts: list[IssueEventFact] = []
    seen_event_ids: set[str] = set()
    for event_index, (raw_event, default_type) in enumerate(event_rows):
        event_mapping = _mapping(raw_event)
        if event_mapping is None:
            malformed = True
            continue
        event = _event_row(
            event_mapping,
            issue_id=issue_id,
            policy=policy,
            source_kind=source_kind,
            default_type=default_type,
            index=event_index,
        )
        if event is None:
            malformed = True
            continue
        if event.event_id in seen_event_ids:
            continue
        seen_event_ids.add(event.event_id)
        event_facts.append(event)
        if event.event_type is IssueEventType.CLOSED and closed_at is None:
            closed_at = event.occurred_at
            state = IssueState.CLOSED

    if created_at is not None and not any(event.event_type is IssueEventType.OPENED for event in event_facts):
        event_facts.append(
            IssueEventFact(
                event_id=f"{issue_id}:opened",
                issue_id=issue_id,
                event_type=IssueEventType.OPENED,
                occurred_at=created_at,
                actor_key=_actor_key(source_kind, author_identity),
                actor_class=author_class,
                classification_reason="issue_author",
                is_state_transition=True,
                source_ref=str(_first(row, "source_ref", "path", "json_pointer") or "") or None,
                source_kind=source_kind,
            )
        )
    if closed_at is not None and not any(event.event_type is IssueEventType.CLOSED for event in event_facts):
        event_facts.append(
            IssueEventFact(
                event_id=f"{issue_id}:closed",
                issue_id=issue_id,
                event_type=IssueEventType.CLOSED,
                occurred_at=closed_at,
                actor_class=ActorClass.UNKNOWN,
                classification_reason="closed_at_field",
                is_state_transition=False,
                source_ref=str(_first(row, "source_ref", "path", "json_pointer") or "") or None,
                source_kind=source_kind,
            )
        )

    comment_events = [event for event in event_facts if event.event_type is IssueEventType.COMMENTED]
    state_events = [event for event in event_facts if event.event_type in {IssueEventType.CLOSED, IssueEventType.REOPENED} and event.is_state_transition]
    actor_known = [event for event in comment_events if event.actor_class is not ActorClass.UNKNOWN]
    has_comments = _bool_value(_first(row, "has_comments", "comments_available"))
    if has_comments is None:
        has_comments = True if comment_events or issue_id in top_comments else None
    has_state_events = _bool_value(_first(row, "has_state_events", "state_events_available"))
    if has_state_events is None:
        has_state_events = bool(state_events)
    has_actor_metadata = _bool_value(_first(row, "has_actor_metadata", "actor_metadata_available"))
    if has_actor_metadata is None:
        has_actor_metadata = bool(comment_events) and len(actor_known) == len(comment_events)
    field_coverage = {
        "created_at": 1.0 if created_at is not None else 0.0,
        "state": 1.0 if state is not IssueState.UNKNOWN else 0.0,
        "closed_at": 1.0 if closed_at is not None else 0.0,
        "comments": 1.0 if has_comments is True else 0.0,
        "actors": len(actor_known) / len(comment_events) if comment_events else 0.0,
        "state_events": 1.0 if has_state_events else 0.0,
    }
    return (
        IssueFact(
            issue_id=issue_id,
            issue_number=str(_first(row, "issue_number", "gh_issue_number", "number") or "") or None,
            url=str(_first(row, "url", "html_url", "issue_url") or "") or None,
            source=str(_first(row, "source", "source_kind") or source_kind),
            source_version=str(_first(row, "source_version", "collector_version") or source_version),
            created_at=created_at,
            updated_at=updated_at,
            state=state,
            closed_at=closed_at,
            author_key=_actor_key(source_kind, author_identity),
            author_class=author_class,
            events=tuple(event_facts),
            is_pull_request=pull_request,
            has_comments=has_comments,
            has_state_events=has_state_events,
            has_actor_metadata=has_actor_metadata,
            field_coverage=field_coverage,
            source_ref=str(_first(row, "source_ref", "path", "json_pointer") or "") or None,
            malformed=malformed,
        ),
        malformed,
    )


def _load_policy_mapping(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("Issues policy must be a YAML mapping")
    analyzer = raw.get("analyzer")
    policy = raw.get("policy")
    if not isinstance(analyzer, Mapping) or not isinstance(policy, Mapping):
        raise ValueError("Issues policy requires analyzer and policy mappings")
    if str(policy.get("policy_revision") or "") != ISSUES_POLICY_REVISION:
        raise ValueError("Issues policy revision does not match the adapter")
    return policy


def load_issues_policy(root: Path | None = None) -> IssuesPolicy:
    """Load and validate the versioned repository-owned Issues policy."""
    import yaml

    resolved_root = Path(root or workspace_root()).resolve()
    path = resolved_root / ISSUES_CONFIG_RELATIVE
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    policy = _load_policy_mapping(raw)
    windows = policy.get("windows") if isinstance(policy.get("windows"), Mapping) else {}
    source = policy.get("source") if isinstance(policy.get("source"), Mapping) else {}
    bot = policy.get("bot_filtering") if isinstance(policy.get("bot_filtering"), Mapping) else {}
    score = policy.get("score") if isinstance(policy.get("score"), Mapping) else {}
    thresholds = policy.get("thresholds") if isinstance(policy.get("thresholds"), Mapping) else {}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = IssuesPolicy(
        policy_revision=str(policy.get("policy_revision") or ISSUES_POLICY_REVISION),
        source_commit=str(source.get("source_commit") or COLLECTOSS_COMMIT),
        analysis_window_days=int(windows.get("analysis_window_days", 90)),
        trend_bucket_days=int(windows.get("trend_bucket_days", 30)),
        maturity_window_days=int(windows.get("maturity_window_days", 30)),
        stale_threshold_days=int(windows.get("stale_threshold_days", 30)),
        old_backlog_threshold_days=int(windows.get("old_backlog_threshold_days", 90)),
        age_buckets_days=tuple(int(item) for item in windows.get("age_buckets_days", (15, 30, 60, 90))),
        stale_activity_event_types=tuple(str(item) for item in windows.get("stale_activity_event_types", ("commented", "reopened"))),
        exclude_issue_author_from_response=bool(policy.get("exclude_issue_author_from_response", True)),
        unknown_actor_policy=str(policy.get("unknown_actor_policy") or "exclude_from_human_response_and_reduce_coverage"),
        known_bot_identities=tuple(str(item) for item in bot.get("known_identities", ())),
        bot_patterns=tuple(str(item) for item in bot.get("patterns", ())),
        minimum_sample=int(thresholds.get("minimum_sample", 5)),
        minimum_coverage=float(thresholds.get("minimum_coverage", 0.80)),
        partial_component_min_coverage=float(thresholds.get("partial_component_min_coverage", 0.50)),
        maximum_findings=int(thresholds.get("maximum_findings", 25)),
        response_median_target_hours=float(thresholds.get("response_median_target_hours", 72)),
        response_median_breach_hours=float(thresholds.get("response_median_breach_hours", 360)),
        response_p75_target_hours=float(thresholds.get("response_p75_target_hours", 168)),
        response_p75_breach_hours=float(thresholds.get("response_p75_breach_hours", 720)),
        close_median_target_hours=float(thresholds.get("close_median_target_hours", 360)),
        close_median_breach_hours=float(thresholds.get("close_median_breach_hours", 1440)),
        close_p75_target_hours=float(thresholds.get("close_p75_target_hours", 720)),
        close_p75_breach_hours=float(thresholds.get("close_p75_breach_hours", 2160)),
        backlog_age_target_hours=float(thresholds.get("backlog_age_target_hours", 720)),
        backlog_age_breach_hours=float(thresholds.get("backlog_age_breach_hours", 2160)),
        responsiveness_weight=float(score.get("responsiveness_weight", 0.30)),
        resolution_weight=float(score.get("resolution_weight", 0.30)),
        backlog_weight=float(score.get("backlog_weight", 0.25)),
        maintenance_weight=float(score.get("maintenance_weight", 0.15)),
        issues_max_share=float(score.get("issues_max_share", 0.25)),
        digest=digest,
    )
    log.info(
        "issues_policy_loaded",
        policy_revision=loaded.policy_revision,
        policy_digest=loaded.digest,
        analysis_window_days=loaded.analysis_window_days,
        minimum_sample=loaded.minimum_sample,
        minimum_coverage=loaded.minimum_coverage,
    )
    return loaded


def normalize_issue_inventory(context: AnalyzerContext, policy: IssuesPolicy) -> IssueCollectionFacts:
    """Normalize available inventory rows without fetching external data."""
    inventory = context.inventory
    as_of = context.as_of_ts.replace(tzinfo=context.as_of_ts.tzinfo or UTC).astimezone(UTC)
    start = as_of - timedelta(days=policy.analysis_window_days)
    source_kind = str(_metadata(inventory, "source_kind", "sourcecraft") or "sourcecraft")
    source_version = str(_metadata(inventory, "source_version", COLLECTOSS_COMMIT) or COLLECTOSS_COMMIT)
    permission_state = str(_metadata(inventory, "permission_state", "unknown") or "unknown").lower()
    issue_key, raw_issues = _find_sequence(
        inventory,
        ("issue_facts", "issues_facts", "sourcecraft_issues", "issue_rows", "issues"),
    )
    _event_key, raw_events = _find_sequence(inventory, ("issue_events", "sourcecraft_issue_events", "events"))
    _comment_key, raw_comments = _find_sequence(inventory, ("issue_comments", "sourcecraft_issue_comments", "comments", "messages"))
    explicit_status = str(_metadata(inventory, "status", "") or "").strip().upper()
    issue_records_available = _bool_value(_metadata(inventory, "records_available", None))
    if issue_records_available is None:
        issue_records_available = True if issue_key is not None else None
    pagination_complete = _bool_value(_metadata(inventory, "pagination_complete", None))
    local_filter = _bool_value(_metadata(inventory, "local_date_filter_applied", None))
    comments_available = _bool_value(_metadata(inventory, "comments_available", None))
    state_events_available = _bool_value(_metadata(inventory, "state_events_available", None))
    records_expected_raw = _metadata(inventory, "records_expected", None)
    try:
        records_expected = int(records_expected_raw) if records_expected_raw is not None else None
    except (TypeError, ValueError):
        records_expected = None

    if permission_state in {"denied", "forbidden", "unauthorized"}:
        return IssueCollectionFacts(
            status=IssueMetricStatus.UNAVAILABLE,
            issues=(),
            as_of=as_of,
            analysis_start=start,
            analysis_end=as_of,
            source_kind=source_kind,
            source_key=issue_key,
            issue_records_available=False,
            comments_available=comments_available,
            state_events_available=state_events_available,
            permission_state=permission_state,
            source_version=source_version,
            limitations=("Issue source permission was denied",),
            diagnostics={"failure_kind": "permission_denied"},
        )

    if raw_issues is None:
        if explicit_status in {"NO_ISSUES", "EMPTY", "MEASURED_EMPTY"} or issue_records_available is False:
            status = IssueMetricStatus.NO_ISSUES
            limitations = ("Issue source is complete and contains no issue records",)
        else:
            status = IssueMetricStatus.UNAVAILABLE
            limitations = ("Granular issue facts were not supplied by the existing collector",)
        return IssueCollectionFacts(
            status=status,
            issues=(),
            as_of=as_of,
            analysis_start=start,
            analysis_end=as_of,
            source_kind=source_kind,
            source_key=issue_key,
            issue_records_available=issue_records_available,
            issue_comment_records_available=raw_comments is not None,
            pagination_complete=pagination_complete,
            local_date_filter_applied=local_filter,
            comments_available=comments_available,
            state_events_available=state_events_available,
            permission_state=permission_state,
            source_version=source_version,
            limitations=limitations,
            diagnostics={"source_shape": "missing_granular_issue_rows"},
        )

    events_by_issue: dict[str, list[object]] = defaultdict(list)
    comments_by_issue: dict[str, list[object]] = defaultdict(list)
    for raw, destination in ((raw_events or (), events_by_issue), (raw_comments or (), comments_by_issue)):
        for item in raw:
            mapping = _mapping(item)
            if mapping is None:
                continue
            item_issue_id = _issue_id(mapping)
            if item_issue_id:
                destination[item_issue_id].append(item)

    facts: list[IssueFact] = []
    malformed_count = 0
    duplicate_count = 0
    excluded_pr_count = 0
    seen_issue_ids: set[str] = set()
    for index, raw_issue in enumerate(raw_issues):
        mapping = _mapping(raw_issue)
        if mapping is None:
            malformed_count += 1
            continue
        raw_issue_id = _issue_id(mapping)
        if raw_issue_id is not None:
            if raw_issue_id in seen_issue_ids:
                duplicate_count += 1
                continue
            seen_issue_ids.add(raw_issue_id)
        fact, malformed = _normalize_issue(
            mapping,
            policy=policy,
            source_kind=source_kind,
            source_version=source_version,
            top_events=events_by_issue,
            top_comments=comments_by_issue,
            index=index,
        )
        if fact is None and (
            _bool_value(_first(mapping, "is_pull_request", "pull_request", "is_pr")) is True
            or _first(mapping, "pull_request_id", "pr_id") not in (None, "")
        ):
            excluded_pr_count += 1
            continue
        if fact is None:
            malformed_count += 1
            continue
        if malformed:
            malformed_count += 1
        facts.append(fact)

    comment_events = [
        event
        for fact in facts
        for event in fact.events
        if event.event_type is IssueEventType.COMMENTED
    ]
    known_actor_events = [event for event in comment_events if event.actor_class is not ActorClass.UNKNOWN]
    actor_coverage = len(known_actor_events) / len(comment_events) if comment_events else 0.0
    if comments_available is None:
        comments_available = raw_comments is not None or bool(comment_events)
    if state_events_available is None:
        state_events_available = any(
            event.event_type in {IssueEventType.CLOSED, IssueEventType.REOPENED}
            and event.is_state_transition
            for fact in facts
            for event in fact.events
        )
    if pagination_complete is None and issue_key is not None:
        pagination_complete = True

    limitations: list[str] = []
    if pagination_complete is False:
        limitations.append("Issue pagination was incomplete")
    if local_filter is False:
        limitations.append("Collector date filtering was not equivalent to the UTC analysis window")
    if malformed_count:
        limitations.append(f"{malformed_count} issue records or events were malformed")
    if duplicate_count:
        limitations.append(f"{duplicate_count} duplicate issue records were ignored")
    if comments_available is not True:
        limitations.append("Issue comments were not fully available")
    if state_events_available is not True:
        limitations.append("Explicit issue state events were not fully available")
    collection_coverage_parts = [1.0]
    if pagination_complete is False:
        collection_coverage_parts.append(0.5)
    elif pagination_complete is None:
        collection_coverage_parts.append(0.8)
    if local_filter is False:
        collection_coverage_parts.append(0.7)
    if records_expected and records_expected > 0:
        collection_coverage_parts.append(min(1.0, len(facts) / records_expected))
    if raw_issues:
        collection_coverage_parts.append(max(0.0, 1.0 - malformed_count / len(raw_issues)))
    coverage = math.prod(collection_coverage_parts)
    confidence = coverage * (actor_coverage if comment_events else 0.75)
    if not facts and raw_issues and malformed_count == len(raw_issues):
        status = IssueMetricStatus.ERROR
    elif pagination_complete is False or local_filter is False or (not raw_issues and (records_expected or 0) > 0):
        status = IssueMetricStatus.PARTIAL
    elif not facts:
        status = IssueMetricStatus.NO_ISSUES
    elif pagination_complete is False or malformed_count:
        status = IssueMetricStatus.PARTIAL
    else:
        status = IssueMetricStatus.MEASURED
    log.info(
        "issues_facts_normalized",
        repo_id=context.repo_id,
        source_key=issue_key,
        status=status.value,
        issue_count=len(facts),
        excluded_pull_request_count=excluded_pr_count,
        malformed_record_count=malformed_count,
        duplicate_record_count=duplicate_count,
        comments_available=comments_available,
        state_events_available=state_events_available,
        actor_metadata_coverage=round(actor_coverage, 4),
        coverage=round(coverage, 4),
    )
    return IssueCollectionFacts(
        status=status,
        issues=tuple(facts),
        as_of=as_of,
        analysis_start=start,
        analysis_end=as_of,
        source_kind=source_kind,
        source_key=issue_key,
        records_observed=len(raw_issues),
        records_expected=records_expected,
        issue_records_available=True,
        issue_comment_records_available=raw_comments is not None,
        pagination_complete=pagination_complete,
        local_date_filter_applied=local_filter,
        comments_available=comments_available,
        state_events_available=state_events_available,
        actor_metadata_coverage=actor_coverage,
        permission_state=permission_state,
        source_version=source_version,
        malformed_record_count=malformed_count,
        duplicate_record_count=duplicate_count,
        excluded_pull_request_count=excluded_pr_count,
        coverage=coverage,
        confidence=confidence,
        limitations=tuple(limitations),
        diagnostics={
        "source_shape": "granular_issue_rows",
        "issue_key": issue_key,
        "event_count": len(raw_events or ()),
        "comment_count": len(raw_comments or ()),
        "duplicate_issue_count": duplicate_count,
        },
    )


__all__ = [
    "CHAOSS_METRICS_REVISION",
    "COLLECTOSS_COMMIT",
    "ISSUES_ANALYZER_VERSION",
    "ISSUES_CONFIG_RELATIVE",
    "ISSUES_POLICY_REVISION",
    "OPEN_DIGGER_REVISION",
    "ActorClass",
    "IssueCollectionFacts",
    "IssueEventFact",
    "IssueEventType",
    "IssueFact",
    "IssueMetricStatus",
    "IssueState",
    "IssuesPolicy",
    "classify_actor",
    "load_issues_policy",
    "normalize_issue_inventory",
]
