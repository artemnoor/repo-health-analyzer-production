import json
from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.native_adapters import (
    parse_criticality_csv,
    parse_qlty,
    parse_repohealth,
    parse_scorecard,
    parse_sokrates,
)


def test_native_fixture_golden_envelope_is_replayable() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures" / "native"
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id="sample-repo",
        head_sha="b" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["local_scan"],
    )
    scorecard = parse_scorecard(json.loads((fixtures / "scorecard" / "sample.json").read_text()), context)
    repohealth = parse_repohealth(json.loads((fixtures / "repohealth" / "sample.json").read_text()), context)
    criticality = parse_criticality_csv((fixtures / "criticality" / "sample.csv").read_text(), context)
    qlty = parse_qlty(json.loads((fixtures / "qlty" / "sarif.json").read_text()), context)
    sokrates = parse_sokrates(json.loads((fixtures / "sokrates" / "sample-export.json").read_text()), context)

    assert scorecard.status is AnalyzerStatus.WARN
    assert repohealth.score == 78
    assert criticality.diagnostics["priority_context"]["criticality_score"] == 0.73125
    assert criticality.score is None
    assert qlty.findings[0].subject == "security/no-secrets"
    assert sokrates.metrics[0].name == "sokrates:TOTAL_LOC"


def test_native_optional_engines_replay_without_binaries() -> None:
    """Qlty/Sokrates parsers remain deterministic when native toolchains are absent."""
    fixtures = Path(__file__).parents[1] / "fixtures" / "native"
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id="sample-repo",
        head_sha="c" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["local_scan"],
    )
    qlty = parse_qlty(json.loads((fixtures / "qlty" / "rdjson.json").read_text()), context)
    sokrates = parse_sokrates(json.loads((fixtures / "sokrates" / "sample-export.json").read_text()), context)
    assert qlty.diagnostics["parser"] == "rdjson"
    assert sokrates.diagnostics["duplication_aggregation"] == "upstream_unique_lines"
