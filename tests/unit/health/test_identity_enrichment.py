import json
from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.identity_adapter import (
    IdentityAdapter,
    IdentityResolver,
)

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _context(*, contributors: dict, raw_facts: list[dict], identity_config: dict | None = None) -> AnalyzerContext:
    inventory = {
        **contributors,
        "raw_facts": raw_facts,
    }
    if identity_config is not None:
        inventory["identity_config"] = identity_config
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id="acme/sample",
        head_sha="a" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["chaoss:events"],
        inventory=inventory,
    )


def test_alias_merge_uses_collectoss_shape_and_keeps_raw_immutable() -> None:
    contributors = json.loads((FIXTURES / "identity" / "contributors.json").read_text(encoding="utf-8"))
    raw = [{"source": "perceval", "event_type": "commit", "stable_event_id": "c1", "payload": {"author": {"email": "123+alice@users.noreply.github.com", "name": "Alice Example"}}}]
    before = json.loads(json.dumps(raw))
    match = IdentityResolver(_context(contributors=contributors, raw_facts=raw)).resolve(raw[0]["payload"]["author"])

    assert match.canonical_contributor_id == "individual-alice"
    assert match.confidence == 0.95
    assert not match.review_required
    assert raw == before


def test_ambiguous_name_stays_separate_and_manual_override_is_explicit() -> None:
    contributors = {
        "contributors": [
            {"cntrb_id": "one", "cntrb_full_name": "Same Name"},
            {"cntrb_id": "two", "cntrb_full_name": "Same Name"},
        ]
    }
    context = _context(contributors=contributors, raw_facts=[], identity_config={"manual_overrides": {"same name": "one"}})
    resolver = IdentityResolver(context)
    overridden = resolver.resolve({"name": "Same Name"})
    assert overridden.canonical_contributor_id == "one"
    assert overridden.confidence == 1.0

    ambiguous = IdentityResolver(_context(contributors=contributors, raw_facts=[])).resolve({"name": "Same Name"})
    assert ambiguous.review_required
    assert ambiguous.confidence < 0.8
    assert ambiguous.canonical_contributor_id.startswith("unresolved:")


def test_adapter_reports_bot_exclusion_and_bus_factor_policy() -> None:
    contributors = json.loads((FIXTURES / "identity" / "contributors.json").read_text(encoding="utf-8"))
    facts = [
        {"source": "perceval", "event_type": "commit", "stable_event_id": "c1", "payload": {"author": {"email": "alice@example.com"}}},
        {"source": "perceval", "event_type": "commit", "stable_event_id": "c2", "payload": {"author": {"email": "alice@example.com"}}},
        {"source": "perceval", "event_type": "ci_run", "stable_event_id": "c3", "payload": {"author": {"login": "release-bot[bot]"}}},
    ]
    result = IdentityAdapter().result(_context(contributors=contributors, raw_facts=facts))

    assert result.status is AnalyzerStatus.WARN
    assert result.diagnostics["bus_factor"] == 1
    assert result.diagnostics["bus_factor_population_scope"] == "non_bot_events"
    assert result.diagnostics["mapping_version"] == "repowise-identity-v1"
