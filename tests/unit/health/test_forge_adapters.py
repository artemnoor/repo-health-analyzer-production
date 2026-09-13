import json
from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.forge_adapter import ForgeAdapter

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _context(payload: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id="acme/sample",
        head_sha="d" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["forge:github"],
        inventory={"forge_payload": payload},
    )


def test_repocrunch_fixture_preserves_raw_ids_cursor_etag_and_utc_timestamps() -> None:
    payload = json.loads((FIXTURES / "forge" / "repocrunch.json").read_text(encoding="utf-8"))
    collection = ForgeAdapter().collect(_context(payload), window="all")

    assert collection.cursor == "page-2"
    assert collection.etag_hits == 1
    assert {fact.stable_event_id for fact in collection.facts} >= {"abc123", "7", "8", "acme/sample"}
    pull_request = next(fact for fact in collection.facts if fact.stable_event_id == "7")
    assert pull_request.updated_at == datetime(2026, 9, 2, 7, tzinfo=UTC)


def test_repocrunch_result_maps_metadata_and_community_without_network() -> None:
    payload = json.loads((FIXTURES / "forge" / "repocrunch.json").read_text(encoding="utf-8"))
    adapter = ForgeAdapter()
    context = _context(payload)

    metadata = adapter.result(context, focus="metadata")
    community = adapter.result(context, focus="community")

    assert metadata.status is AnalyzerStatus.PASS
    assert {metric.name for metric in metadata.metrics} >= {"forge:stars", "forge:primary_language", "forge:architecture:has_tests"}
    assert community.status is AnalyzerStatus.PASS
    assert {metric.name for metric in community.metrics} >= {"forge:open_issues", "forge:contributors", "forge:events:pull_request"}
    assert community.diagnostics["raw_fact_count"] == 4


def test_repocrunch_permission_denial_is_unknown_not_false_negative() -> None:
    payload = json.loads((FIXTURES / "forge" / "permission-unknown.json").read_text(encoding="utf-8"))
    result = ForgeAdapter().result(_context(payload), focus="community")

    assert result.status is AnalyzerStatus.INCONCLUSIVE
    assert result.diagnostics["permission_state"] == "unknown"
    assert "403" in result.findings[0].reason
    assert result.score is None
