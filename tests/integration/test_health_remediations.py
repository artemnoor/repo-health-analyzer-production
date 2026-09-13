from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext
from repowise.core.analysis.health.integrations.finding_merge import deduplicate_findings
from repowise.core.analysis.health.integrations.native_adapters import (
    parse_repohealth,
    parse_scorecard,
)


def _context(tmp_path: Path) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=tmp_path,
        repo_id="remediation-fixture",
        head_sha="a" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["local_scan"],
    )


def test_repohealth_and_scorecard_preserve_source_remediation_and_metric_dimensions(tmp_path: Path) -> None:
    repohealth = parse_repohealth(
        {
            "version": "fixture",
            "score": 50,
            "checks": [{"id": "TST-01", "category": "tests", "status": "none"}],
            "suggestions": [{"check_id": "TST-01", "impact": 4, "message": "Add tests"}],
        },
        _context(tmp_path),
    )
    scorecard = parse_scorecard(
        {"version": "fixture", "checks": [{"name": "Branch-Protection", "score": 5, "remediation": "Require reviews"}]},
        _context(tmp_path),
    )

    assert repohealth.metrics[0].dimension == "tests"
    assert repohealth.metrics[0].score == 0
    assert repohealth.findings[0].remediation == "Add tests"
    assert repohealth.findings[0].raw_impact == 4
    assert scorecard.metrics[0].dimension == "delivery"
    assert scorecard.findings[0].remediation == "Require reviews"


def test_duplicate_findings_merge_evidence_without_losing_remediation(tmp_path: Path) -> None:
    context = _context(tmp_path)
    first = parse_repohealth({"checks": [{"id": "DOC-1", "category": "docs", "status": "none", "suggestion": "Add README"}]}, context)
    second = parse_repohealth({"checks": [{"id": "DOC-1", "category": "docs", "status": "none", "suggestion": "Add README"}]}, context)

    merged = deduplicate_findings((first, second))

    assert len(merged[0].findings) == 1
    assert len(merged[1].findings) == 0
    assert merged[0].findings[0].remediation == "Add README"
