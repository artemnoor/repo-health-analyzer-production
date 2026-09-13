from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.forge_adapter import RawFact
from repowise.core.analysis.health.integrations.temporal_adapter import (
    EventNormalizer,
    TemporalAdapter,
    build_temporal_window,
    materialized_rollups,
)


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id="sample",
        head_sha="b" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["chaoss:events"],
        inventory=inventory,
    )


def test_normalizer_preserves_offset_and_is_idempotent() -> None:
    context = _context({})
    raw = {"source": "perceval", "event_type": "commit", "stable_event_id": "c1", "updated_at": "2026-09-09T12:00:00+03:00", "payload": {"author": "redacted"}}
    normalizer = EventNormalizer(context)
    first = normalizer.normalize(raw)
    second = normalizer.normalize(raw)

    assert first.normalized_ts == datetime(2026, 9, 9, 9, tzinfo=UTC)
    assert first.original_offset_minutes == 180
    assert not first.timestamp_corrected
    assert first == second
    assert first.payload["author"] == "redacted"


def test_as_of_window_excludes_mass_edit_and_applies_exponential_decay() -> None:
    context = _context({})
    normalizer = EventNormalizer(context)
    facts = [
        normalizer.normalize(RawFact("git", "sample", "commit", "old", {"lines_added": 1}, datetime(2026, 8, 1, tzinfo=UTC))),
        normalizer.normalize(RawFact("git", "sample", "commit", "mass", {"lines_added": 5000}, datetime(2026, 9, 1, tzinfo=UTC))),
    ]
    window = build_temporal_window(facts, as_of_ts=context.as_of_ts, window_days=90, half_life_days=30, mass_edit_threshold=1000)

    assert window.included_event_count == 1
    assert window.excluded_mass_edit_count == 1
    assert 0 < window.weight(facts[0].normalized_ts) < 1


def test_stale_materialized_rollup_is_explicit() -> None:
    context = _context({"materialized_views": {"contributors_daily": {"grain": "daily", "unique_key": ["repo_id", "date", "contributor_id"], "refreshed_at": "2026-09-01T00:00:00Z", "stale_after_seconds": 3600, "refresh_mode": "concurrent"}}})
    rollups = materialized_rollups(context)
    result = TemporalAdapter().result(context)

    assert rollups[0].is_stale
    assert result.status is AnalyzerStatus.WARN
    assert result.diagnostics["rollups"][0]["status"] == "stale"
