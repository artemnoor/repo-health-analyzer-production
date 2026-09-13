import sys
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
from repowise.core.analysis.health.integrations.process import NativeProcess

FIXTURES = Path(__file__).parents[2] / "fixtures" / "native"


def _context(tmp_path: Path) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=tmp_path,
        repo_id="sample",
        head_sha="a" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["local_scan"],
    )


def test_scorecard_parser_preserves_scorecard_inconclusive_and_location(tmp_path: Path) -> None:
    import json

    payload = json.loads((FIXTURES / "scorecard" / "sample.json").read_text(encoding="utf-8"))
    result = parse_scorecard(payload, _context(tmp_path), raw_ref="native://fixture/scorecard")

    assert result.status is AnalyzerStatus.WARN
    assert result.score == 75.0
    assert result.findings[0].location.path == ".github/workflows/ci.yml"
    assert result.findings[0].location.line_start == 12
    assert result.limitations[0].kind == "insufficient_denominator"
    assert result.raw_payload_ref == "native://fixture/scorecard"


def test_repohealth_parser_maps_checks_to_findings_and_keeps_0_100_score(tmp_path: Path) -> None:
    import json

    payload = json.loads((FIXTURES / "repohealth" / "sample.json").read_text(encoding="utf-8"))
    result = parse_repohealth(payload, _context(tmp_path))

    assert result.score == 78
    assert result.status is AnalyzerStatus.WARN
    assert {finding.subject for finding in result.findings} == {"TST-01", "CI-01"}


def test_criticality_is_priority_context_and_never_health_score(tmp_path: Path) -> None:
    raw = (FIXTURES / "criticality" / "sample.csv").read_text(encoding="utf-8")
    result = parse_criticality_csv(raw, _context(tmp_path))

    assert result.status is AnalyzerStatus.PASS
    assert result.score is None
    assert result.diagnostics["priority_context"]["criticality_score"] == 0.73125
    assert result.metrics[0].name == "criticality_signal:repo.name" or result.metrics[0].name.startswith("criticality_signal:")


def test_malformed_native_payloads_are_inconclusive_or_error_without_zero(tmp_path: Path) -> None:
    import json

    malformed = json.loads((FIXTURES / "scorecard" / "malformed.json").read_text(encoding="utf-8"))
    result = parse_scorecard(malformed, _context(tmp_path))
    missing_score = parse_criticality_csv(
        (FIXTURES / "criticality" / "malformed.csv").read_text(encoding="utf-8"), _context(tmp_path)
    )

    assert result.status is AnalyzerStatus.ERROR
    assert result.score is None
    assert missing_score.status is AnalyzerStatus.INCONCLUSIVE
    assert missing_score.score is None


def test_native_process_bounds_output_and_reports_timeout(tmp_path: Path) -> None:
    context = _context(tmp_path)
    bounded = NativeProcess(output_cap=32).run(
        "fixture",
        sys.executable,
        ["-c", "print('x' * 200)"],
        context,
    )
    timed_out = NativeProcess(output_cap=32).run(
        "fixture-timeout",
        sys.executable,
        ["-c", "import time; time.sleep(2)"],
        context,
        timeout=0.05,
    )

    assert bounded.truncated is True
    assert len(bounded.stdout.encode("utf-8")) <= 32
    assert timed_out.timed_out is True


def test_qlty_sarif_preserves_rule_location_fingerprint_and_tool_version(tmp_path: Path) -> None:
    import json

    payload = json.loads((FIXTURES / "qlty" / "sarif.json").read_text(encoding="utf-8"))
    result = parse_qlty(payload, _context(tmp_path), raw_ref="native://fixture/qlty-sarif")

    assert result.status is AnalyzerStatus.FAIL
    assert result.findings[0].subject == "security/no-secrets"
    assert result.findings[0].location.path == "src/config.py"
    assert result.findings[0].location.line_start == 12
    assert result.findings[0].evidence_refs[0].tool_version == "0.1-fixture"
    assert result.findings[0].evidence_refs[0].snippet_hash == "fixture-secret-12"
    assert result.diagnostics["cache_provenance"]["target_tree_sha"] == "a" * 40
    assert len(result.diagnostics["cache_key"]) == 64
    assert result.raw_payload_ref == "native://fixture/qlty-sarif"


def test_qlty_rdjson_maps_reviewdog_range_and_remediation(tmp_path: Path) -> None:
    import json

    payload = json.loads((FIXTURES / "qlty" / "rdjson.json").read_text(encoding="utf-8"))
    result = parse_qlty(payload, _context(tmp_path))

    assert result.status is AnalyzerStatus.WARN
    assert result.findings[0].severity == "medium"
    assert result.findings[0].location.path == "src/main.py"
    assert result.findings[0].location.line_start == 4
    assert result.findings[0].location.line_end == 4
    assert result.findings[0].remediation.endswith("trailing-whitespace")


def test_qlty_malformed_output_is_error_without_health_score(tmp_path: Path) -> None:
    import json

    payload = json.loads((FIXTURES / "qlty" / "malformed.json").read_text(encoding="utf-8"))
    result = parse_qlty(payload, _context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert result.score is None


def test_sokrates_export_maps_metrics_duplication_bus_factor_and_heuristic_edges(tmp_path: Path) -> None:
    import json

    payload = json.loads((FIXTURES / "sokrates" / "sample-export.json").read_text(encoding="utf-8"))
    result = parse_sokrates(payload, _context(tmp_path), raw_ref="native://fixture/sokrates")

    metric_values = {metric.name: metric.value for metric in result.metrics}
    dependency = next(finding for finding in result.findings if finding.dimension == "dependencies")
    assert result.status is AnalyzerStatus.WARN
    assert metric_values["sokrates:duplication_density"] == 15.0
    assert metric_values["sokrates:bus_factor_50_percent"] == 1
    assert dependency.confidence == 0.6
    assert dependency.evidence_refs[0].path == "src/api.py"
    assert result.raw_payload_ref == "native://fixture/sokrates"


def test_sokrates_malformed_export_is_error_and_empty_export_is_inconclusive(tmp_path: Path) -> None:
    import json

    malformed = json.loads((FIXTURES / "sokrates" / "malformed.json").read_text(encoding="utf-8"))
    result = parse_sokrates(malformed, _context(tmp_path))
    unsupported = parse_sokrates({"exportVersion": "future"}, _context(tmp_path))

    assert result.status is AnalyzerStatus.ERROR
    assert unsupported.status is AnalyzerStatus.INCONCLUSIVE
