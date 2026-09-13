from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    MetricValue,
)


def _definition() -> AnalyzerDefinition:
    return AnalyzerDefinition(
        id="quality.baseline",
        version="1.0.0",
        category="quality",
        dimensions=["maintainability"],
        source_commit="0" * 40,
    )


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        source="repowise",
        source_commit="0" * 40,
        path="src/app.py",
        line_start=10,
        line_end=14,
        json_pointer="/findings/0",
        snippet_hash="sha256:abc",
        collected_at=datetime(2026, 9, 10, tzinfo=UTC),
        confidence=0.9,
    )


def test_result_round_trip_is_versioned_and_preserves_evidence_location() -> None:
    evidence = _evidence()
    result = AnalyzerResult(
        analyzer_id="quality.baseline",
        analyzer_version="1.0.0",
        status=AnalyzerStatus.WARN,
        score=71.5,
        metrics=(MetricValue(name="nloc", value=42, unit="lines", denominator=1, evidence_refs=(evidence,)),),
        findings=(
            Finding(
                id="complex-method:src/app.py:10",
                analyzer_id="quality.baseline",
                subject="src/app.py",
                dimension="maintainability",
                severity="medium",
                confidence=0.9,
                reason="method is too complex",
                evidence_refs=(evidence,),
                location=FindingLocation(path="src/app.py", line_start=10, line_end=14, symbol="run"),
                remediation="split the method",
                raw_impact=8.0,
                applied_impact=5.0,
            ),
        ),
        evidence=(evidence,),
        source_versions={"repowise": "1.0.0"},
        available_weight=1,
        total_weight=1,
        raw_payload_ref="cache://quality-baseline.json",
    )

    restored = AnalyzerResult.model_validate_json(result.model_dump_json())

    assert restored.schema_version == 1
    assert restored.findings[0].location.line_start == 10
    assert restored.evidence[0].json_pointer == "/findings/0"
    assert restored.model_dump(mode="json")["schema_version"] == 1


@pytest.mark.parametrize("status", [AnalyzerStatus.SKIPPED, AnalyzerStatus.ERROR])
def test_skipped_and_error_results_cannot_fabricate_a_score(status: AnalyzerStatus) -> None:
    with pytest.raises(ValidationError, match="score must be absent"):
        AnalyzerResult(
            analyzer_id="x",
            analyzer_version="1",
            status=status,
            score=0,
        )


def test_missing_denominator_is_explicitly_inconclusive_not_zero() -> None:
    result = AnalyzerResult.insufficient_denominator(_definition(), "no production files were measurable", total_weight=10)

    assert result.status is AnalyzerStatus.INCONCLUSIVE
    assert result.score is None
    assert result.limitations[0].kind == "insufficient_denominator"


def test_context_and_definition_have_stable_sorted_capabilities() -> None:
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id="demo",
        head_sha="abc",
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["git", "local_scan", "git"],
    )
    definition = AnalyzerDefinition(
        id="demo",
        version="1",
        category="demo",
        dimensions=["z", "a"],
        requires=["git", "local_scan"],
    )

    assert context.capabilities == ("git", "local_scan")
    assert definition.dimensions == ("a", "z")
