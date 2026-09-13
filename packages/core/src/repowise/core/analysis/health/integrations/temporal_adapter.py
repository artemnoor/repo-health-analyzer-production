"""Deterministic event normalization and time-window enrichment.

The timestamp repair routine is imported from the copied CollectOSS DB layer;
this module adds the replay envelope, UTC window policy and materialized-view
freshness state around it.  Raw ``RawFact`` objects are never edited.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import structlog

from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    Limitation,
    MetricValue,
)
from .forge_adapter import RawFact
from .process import workspace_root

log = structlog.get_logger("temporal.normalize")

COLLECTOSS_COMMIT = "339edc520e79dd1728ca19255d94a05a4a107df1"
PERCEVAL_COMMIT = "cb07eaafa4c67561ca24ca8f9bb96783c312b5aa9"
TEMPORAL_POLICY_VERSION = "utc-as-of-v1"
TEMPORAL_ANALYZER_ID = "events.temporal"
TEMPORAL_DEFINITION = AnalyzerDefinition(
    id=TEMPORAL_ANALYZER_ID,
    version=TEMPORAL_POLICY_VERSION,
    category="event-temporal-enrichment",
    dimensions=("activity", "churn", "delivery", "community"),
    requires=("chaoss:events",),
    phase=68,
    cost=20,
    timeout=45,
    cache_policy="read_write",
    source_commit=COLLECTOSS_COMMIT,
    enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
)

_OFFSET_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


@dataclass(frozen=True)
class NormalizedFact:
    """UTC-derived event view with the original timestamp retained."""

    source: str
    repo_id: str
    event_type: str
    stable_event_id: str
    original_timestamp: str | None
    normalized_ts: datetime
    original_offset_minutes: int | None
    timestamp_corrected: bool
    payload: Mapping[str, Any]
    source_version: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    normalization_policy: str = TEMPORAL_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class TemporalWindow:
    """An explicit, replayable interval used by every temporal metric."""

    as_of_ts: datetime
    start_ts: datetime
    end_ts: datetime
    decay: float
    included_event_count: int
    excluded_mass_edit_count: int
    window_days: int
    policy_version: str = TEMPORAL_POLICY_VERSION

    @property
    def included_count(self) -> int:
        return self.included_event_count

    def weight(self, event_ts: datetime) -> float:
        age_days = max((self.as_of_ts - event_ts).total_seconds() / 86400.0, 0.0)
        return math.exp(-self.decay * age_days)


@dataclass(frozen=True)
class MaterializedRollup:
    """Refresh contract for a daily/weekly derived view."""

    view_name: str
    grain: str
    unique_key: tuple[str, ...]
    refreshed_at: datetime | None
    stale_after_seconds: int
    refresh_mode: str = "concurrent"
    status: str = "unknown"

    @property
    def is_stale(self) -> bool:
        if self.status in {"stale", "failed"}:
            return True
        if self.refreshed_at is None:
            return self.status not in {"fresh", "current"}
        return False


def _collectoss_timestamp_source() -> Path:
    source = workspace_root() / "vendor" / "collectoss"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def _copied_correct_timestamp(value: str, fallback: str) -> tuple[str, bool]:
    """Use CollectOSS's exact timezone repair for its DB-shaped timestamps."""
    if not value or " " not in value:
        return value, False
    try:
        _collectoss_timestamp_source()
        from collectoss.application.db.timestamp_utils import correct_timestamp

        corrected = correct_timestamp(value, fallback=fallback, logger=logging.getLogger("collectoss.timestamp"))
        return corrected, corrected != value
    except (ImportError, OSError):
        return value, False


def _parse_timestamp(value: object, *, fallback: datetime) -> tuple[datetime, bool, str | None, int | None]:
    if isinstance(value, datetime):
        original = value.isoformat()
        offset = value.utcoffset()
        minutes = int(offset.total_seconds() // 60) if offset else 0
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC), False, original, minutes
    original = str(value).strip() if value not in (None, "") else None
    if not original:
        return fallback, True, None, None
    offset_match = _OFFSET_RE.search(original)
    offset_text = offset_match.group(0) if offset_match else None
    minutes: int | None = None
    if offset_text and offset_text != "Z":
        sign = 1 if offset_text[0] == "+" else -1
        digits = offset_text[1:].replace(":", "")
        try:
            minutes = sign * (int(digits[:2]) * 60 + int(digits[2:]))
        except (ValueError, IndexError):
            minutes = None
    parsed_text = original.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(parsed_text)
        return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC), False, original, minutes
    except ValueError:
        pass
    corrected, _changed = _copied_correct_timestamp(original, fallback=fallback.strftime("%Y-%m-%d %H:%M:%S +0000"))
    try:
        parsed = datetime.strptime(corrected, "%Y-%m-%d %H:%M:%S %z")
        return parsed.astimezone(UTC), True, original, minutes
    except ValueError:
        log.warning("malformed_timestamp fallback=as_of")
        return fallback, True, original, minutes


def _as_utc(value: object, fallback: datetime) -> datetime | None:
    if value in (None, ""):
        return None
    parsed, _changed, _original, _offset = _parse_timestamp(value, fallback=fallback)
    return parsed


def raw_facts_from_context(context: AnalyzerContext) -> tuple[RawFact, ...]:
    """Read supplied raw snapshots, optionally replaying Forge/CHAOSS fixtures."""
    result: list[RawFact] = []
    supplied = context.inventory.get("raw_facts")
    if isinstance(supplied, Iterable) and not isinstance(supplied, (str, bytes, Mapping)):
        for item in supplied:
            if isinstance(item, RawFact):
                result.append(item)
            elif isinstance(item, Mapping):
                updated = item.get("updated_at")
                result.append(
                    RawFact(
                        source=str(item.get("source") or "replay"),
                        repo_id=context.repo_id,
                        event_type=str(item.get("event_type") or item.get("type") or "event"),
                        stable_event_id=str(item.get("stable_event_id") or item.get("id") or len(result)),
                        payload=dict(item.get("payload") or item),
                        updated_at=updated if isinstance(updated, datetime) else _as_utc(updated, context.as_of_ts),
                        window_start=_as_utc(item.get("window_start"), context.as_of_ts),
                        window_end=_as_utc(item.get("window_end"), context.as_of_ts),
                        cursor=str(item.get("cursor")) if item.get("cursor") else None,
                        permission_state=str(item.get("permission_state") or "granted"),
                        source_version=str(item.get("source_version") or "replay"),
                    )
                )
    if result:
        return tuple(result)
    if isinstance(context.inventory.get("forge_payload"), Mapping):
        from .forge_adapter import ForgeAdapter

        result.extend(ForgeAdapter().collect(context).facts)
    if isinstance(context.inventory.get("chaoss_rows"), Mapping):
        from .chaoss_adapter import ChaossAdapter

        result.extend(ChaossAdapter().collect(context))
    return tuple(result)


class EventNormalizer:
    """Normalize a raw event deterministically and without mutation."""

    def __init__(self, context: AnalyzerContext) -> None:
        self.context = context

    def normalize(self, raw_fact: RawFact | Mapping[str, Any]) -> NormalizedFact:
        if isinstance(raw_fact, RawFact):
            source = raw_fact.source
            repo_id = raw_fact.repo_id
            event_type = raw_fact.event_type
            event_id = raw_fact.stable_event_id
            payload = dict(raw_fact.payload)
            timestamp = raw_fact.updated_at or payload.get("timestamp") or payload.get("created_at")
            source_version = raw_fact.source_version
            window_start = raw_fact.window_start
            window_end = raw_fact.window_end
        else:
            source = str(raw_fact.get("source") or "replay")
            repo_id = self.context.repo_id
            event_type = str(raw_fact.get("event_type") or raw_fact.get("type") or "event")
            event_id = str(raw_fact.get("stable_event_id") or raw_fact.get("id") or "0")
            payload = dict(raw_fact.get("payload") or raw_fact)
            timestamp = raw_fact.get("updated_at") or payload.get("timestamp") or payload.get("created_at")
            source_version = str(raw_fact.get("source_version") or "replay")
            window_start = _as_utc(raw_fact.get("window_start"), self.context.as_of_ts)
            window_end = _as_utc(raw_fact.get("window_end"), self.context.as_of_ts)
        normalized, corrected, original, offset = _parse_timestamp(timestamp, fallback=self.context.as_of_ts)
        log.debug(
            "event_normalized repo_id=%s event_type=%s corrected=%s has_offset=%s",
            self.context.repo_id,
            event_type,
            corrected,
            offset is not None,
        )
        return NormalizedFact(
            source=source,
            repo_id=repo_id,
            event_type=event_type,
            stable_event_id=event_id,
            original_timestamp=original,
            normalized_ts=normalized,
            original_offset_minutes=offset,
            timestamp_corrected=corrected,
            payload=payload,
            source_version=source_version,
            window_start=window_start,
            window_end=window_end,
        )


def _is_mass_edit(fact: NormalizedFact, threshold: int) -> bool:
    if bool(fact.payload.get("is_mass_edit")):
        return True
    try:
        churn = int(fact.payload.get("lines_added") or 0) + int(fact.payload.get("lines_removed") or fact.payload.get("lines_deleted") or 0)
        files = int(fact.payload.get("files_changed") or fact.payload.get("file_count") or 0)
    except (TypeError, ValueError):
        return False
    return churn >= threshold or files >= max(25, threshold // 20)


def build_temporal_window(
    facts: Iterable[NormalizedFact],
    *,
    as_of_ts: datetime,
    window_days: int = 90,
    half_life_days: float = 30.0,
    mass_edit_threshold: int = 1000,
) -> TemporalWindow:
    as_of = as_of_ts.astimezone(UTC)
    start = as_of - timedelta(days=max(1, int(window_days)))
    included = 0
    excluded_mass_edit = 0
    for fact in facts:
        if start <= fact.normalized_ts <= as_of:
            if _is_mass_edit(fact, mass_edit_threshold):
                excluded_mass_edit += 1
            else:
                included += 1
    decay = math.log(2.0) / max(float(half_life_days), 0.1)
    log.debug(
        "window_built start=%s end=%s included=%d mass_edit=%d decay=%.8f",
        start.isoformat(),
        as_of.isoformat(),
        included,
        excluded_mass_edit,
        decay,
    )
    return TemporalWindow(as_of, start, as_of, decay, included, excluded_mass_edit, max(1, int(window_days)))


def _rollup_from_row(name: str, row: Mapping[str, Any], *, as_of: datetime) -> MaterializedRollup:
    grain = str(row.get("grain") or ("weekly" if "week" in name else "daily"))
    unique = row.get("unique_key") or row.get("unique_key_columns") or ("repo_id", "period_start", "contributor_id")
    if isinstance(unique, str):
        unique = (unique,)
    refreshed = _as_utc(row.get("refreshed_at") or row.get("last_refresh"), as_of)
    stale_after = row.get("stale_after_seconds", 86400)
    try:
        stale_after = int(stale_after)
    except (TypeError, ValueError):
        stale_after = 86400
    status = str(row.get("status") or ("fresh" if refreshed else "unknown"))
    if refreshed and as_of - refreshed > timedelta(seconds=stale_after):
        status = "stale"
    return MaterializedRollup(name, grain, tuple(str(item) for item in unique), refreshed, stale_after, str(row.get("refresh_mode") or "concurrent"), status)


def materialized_rollups(context: AnalyzerContext) -> tuple[MaterializedRollup, ...]:
    """Return daily/weekly rollups with the copied CollectOSS refresh policy."""
    supplied = context.inventory.get("materialized_views")
    rows: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(supplied, Mapping):
        rows = [(str(name), value) for name, value in supplied.items() if isinstance(value, Mapping)]
    elif isinstance(supplied, Iterable) and not isinstance(supplied, (str, bytes)):
        rows = [(str(value.get("view_name") or value.get("name") or "rollup"), value) for value in supplied if isinstance(value, Mapping)]
    if not rows:
        rows = [
            ("contributors_daily", {"grain": "daily", "unique_key": ("repo_id", "date", "contributor_id"), "status": "unknown"}),
            ("contributors_weekly", {"grain": "weekly", "unique_key": ("repo_id", "week", "contributor_id"), "status": "unknown"}),
        ]
    return tuple(_rollup_from_row(name, row, as_of=context.as_of_ts) for name, row in sorted(rows))


def _evidence(context: AnalyzerContext, fact: NormalizedFact) -> EvidenceRef:
    return EvidenceRef(
        source=fact.source,
        source_commit=fact.source_version,
        json_pointer=f"/events/{fact.event_type}/{fact.stable_event_id}",
        collected_at=fact.normalized_ts,
        confidence=1.0,
        redaction="partial",
    )


class TemporalAdapter:
    definition = TEMPORAL_DEFINITION

    def result(self, context: AnalyzerContext) -> AnalyzerResult:
        raw = raw_facts_from_context(context)
        normalizer = EventNormalizer(context)
        normalized = tuple(normalizer.normalize(fact) for fact in raw)
        config = context.inventory.get("temporal_config") if isinstance(context.inventory.get("temporal_config"), Mapping) else {}
        window = build_temporal_window(
            normalized,
            as_of_ts=context.as_of_ts,
            window_days=int(config.get("window_days", 90)),
            half_life_days=float(config.get("half_life_days", 30.0)),
            mass_edit_threshold=int(config.get("mass_edit_threshold", 1000)),
        )
        in_window = [fact for fact in normalized if window.start_ts <= fact.normalized_ts <= window.end_ts and not _is_mass_edit(fact, int(config.get("mass_edit_threshold", 1000)))]
        production = [fact for fact in in_window if not bool(fact.payload.get("is_test")) and not str(fact.payload.get("path") or fact.payload.get("file_path") or "").lower().startswith(("test/", "tests/"))]
        weighted = sum(window.weight(fact.normalized_ts) for fact in in_window)
        evidence = tuple(_evidence(context, fact) for fact in in_window)
        metrics = (
            MetricValue(name="events:raw_count", dimension="history", value=len(raw), unit="events", denominator=len(raw), evidence_refs=evidence[:1]),
            MetricValue(name="events:window_count", dimension="history", value=len(in_window), unit="events", denominator=len(raw), evidence_refs=evidence[:1]),
            MetricValue(name="events:production_count", dimension="history", value=len(production), unit="events", denominator=len(in_window), evidence_refs=evidence[:1]),
            MetricValue(name="events:decayed_activity", dimension="history", value=weighted, unit="weighted_events", denominator=len(in_window), evidence_refs=evidence[:1]),
            MetricValue(name="events:mass_edit_excluded", dimension="history", value=window.excluded_mass_edit_count, unit="events", denominator=len(normalized), evidence_refs=evidence[:1]),
        )
        findings: list[Finding] = []
        corrected = [fact for fact in normalized if fact.timestamp_corrected]
        if corrected:
            findings.append(
                Finding(
                    id=f"{TEMPORAL_ANALYZER_ID}:timestamp-corrections",
                    analyzer_id=TEMPORAL_ANALYZER_ID,
                    subject="events",
                    dimension="activity",
                    severity="medium",
                    confidence=1.0,
                    reason="Some event timestamps required the copied CollectOSS timezone correction or replay fallback.",
                    evidence_refs=tuple(_evidence(context, fact) for fact in corrected[:10]),
                    remediation="Normalize event timestamps at collection time and review the affected source records.",
                )
            )
        rollups = materialized_rollups(context)
        stale = [rollup for rollup in rollups if rollup.is_stale]
        if stale:
            findings.append(
                Finding(
                    id=f"{TEMPORAL_ANALYZER_ID}:stale-rollups",
                    analyzer_id=TEMPORAL_ANALYZER_ID,
                    subject="materialized-views",
                    dimension="activity",
                    severity="medium",
                    confidence=1.0,
                    reason="A daily or weekly materialized rollup is stale or has no known refresh state; derived metrics are not current.",
                    remediation="Refresh the copied CollectOSS materialized views concurrently and record their unique-key refresh state.",
                )
            )
        status = AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS if raw else AnalyzerStatus.INCONCLUSIVE
        limitation = () if raw else (Limitation(reason="No raw events were supplied for temporal replay", kind="insufficient_denominator"),)
        raw_ref = hashlib.sha256("|".join(fact.stable_event_id for fact in raw).encode()).hexdigest() if raw else None
        return AnalyzerResult(
            analyzer_id=TEMPORAL_ANALYZER_ID,
            analyzer_version=TEMPORAL_POLICY_VERSION,
            status=status,
            metrics=metrics if raw else (),
            findings=tuple(findings),
            evidence=evidence,
            limitations=limitation,
            source_versions={"collectoss": COLLECTOSS_COMMIT, "perceval": PERCEVAL_COMMIT},
            available_weight=float(len(metrics) if raw else 0),
            total_weight=float(len(metrics)),
            raw_payload_ref=f"events://{raw_ref}" if raw_ref else None,
            diagnostics={
                "normalization_policy": TEMPORAL_POLICY_VERSION,
                "as_of_ts": window.as_of_ts.isoformat(),
                "start_ts": window.start_ts.isoformat(),
                "end_ts": window.end_ts.isoformat(),
                "decay": window.decay,
                "window_days": window.window_days,
                "included_event_count": window.included_event_count,
                "excluded_mass_edit_count": window.excluded_mass_edit_count,
                "corrected_timestamp_count": len(corrected),
                "rollups": [
                    {
                        "view_name": rollup.view_name,
                        "grain": rollup.grain,
                        "unique_key": rollup.unique_key,
                        "status": rollup.status,
                        "refresh_mode": rollup.refresh_mode,
                    }
                    for rollup in rollups
                ],
                "source_event_ids": [fact.stable_event_id for fact in normalized],
            },
        )


def temporal_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return TemporalAdapter().result(context)


def register_temporal_adapters(registry: Any) -> None:
    if TEMPORAL_ANALYZER_ID not in registry.ids():
        registry.register(TEMPORAL_DEFINITION, temporal_adapter)


__all__ = [
    "COLLECTOSS_COMMIT",
    "TEMPORAL_ANALYZER_ID",
    "TEMPORAL_DEFINITION",
    "TEMPORAL_POLICY_VERSION",
    "EventNormalizer",
    "MaterializedRollup",
    "NormalizedFact",
    "TemporalAdapter",
    "TemporalWindow",
    "build_temporal_window",
    "materialized_rollups",
    "raw_facts_from_context",
    "register_temporal_adapters",
    "temporal_adapter",
]
