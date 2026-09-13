from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    MetricValue,
)
from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry
from repowise.core.analysis.health.models import (
    HealthFileMetricData,
    HealthFindingData,
    HealthReport,
    Severity,
)


def test_fake_analyzer_produces_one_evidence_backed_composition_envelope(tmp_path: Path) -> None:
    registry = AnalyzerRegistry()
    definition = AnalyzerDefinition(
        id="fake.baseline",
        version="1.0.0",
        category="quality",
        requires=["local_scan"],
        cache_policy="read_write",
    )

    def fake(context: AnalyzerContext) -> AnalyzerResult:
        evidence = EvidenceRef(
            source="fake",
            path="README.md",
            collected_at=context.as_of_ts,
        )
        return AnalyzerResult(
            analyzer_id="fake.baseline",
            analyzer_version="1.0.0",
            status=AnalyzerStatus.PASS,
            score=92,
            metrics=(MetricValue(name="files", value=1, denominator=1, evidence_refs=(evidence,)),),
            evidence=(evidence,),
            source_versions={"fake": "1.0.0"},
            available_weight=1,
            total_weight=1,
        )

    registry.register(definition, fake)
    context = AnalyzerContext(
        repo_path=tmp_path,
        repo_id="demo",
        head_sha="abc",
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["local_scan"],
        cache_dir=tmp_path / ".cache",
    )

    result = registry.run_all(context)[0]
    restored = AnalyzerResult.model_validate_json(result.model_dump_json())

    assert restored.status is AnalyzerStatus.PASS
    assert restored.metrics[0].name == "files"
    assert restored.evidence[0].source == "fake"
    assert restored.limitations == ()


def test_repowise_adapter_maps_existing_report_without_reimplementing_scoring(monkeypatch, tmp_path: Path) -> None:
    import repowise.core.analysis.health.integrations.repowise_adapter as adapter_module

    report = HealthReport(
        repo_id="",
        analyzed_at=datetime(2020, 1, 1, tzinfo=UTC),
        metrics=[
            HealthFileMetricData(
                file_path="src/app.py",
                score=7.5,
                max_ccn=3,
                max_nesting=2,
                nloc=40,
                has_test_file=True,
            ),
        ],
        findings=[
            HealthFindingData(
                biomarker_type="complex_method",
                severity=Severity.HIGH,
                file_path="src/app.py",
                function_name="run",
                line_start=10,
                line_end=14,
                details={},
                health_impact=2.5,
            ),
        ],
        kpis={"average_health": 7.5},
    )

    class ExistingHealthAnalyzer:
        def __init__(self, *args, **kwargs) -> None:
            self.kwargs = kwargs

        def analyze(self, config, **kwargs):
            self.kwargs = kwargs
            return report

    monkeypatch.setattr(adapter_module, "HealthAnalyzer", ExistingHealthAnalyzer)
    context = AnalyzerContext(
        repo_path=tmp_path,
        repo_id="demo",
        head_sha="abc",
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        scope="all",
        mode="diff",
        capabilities=["local_scan"],
        inventory={"graph": None, "parsed_files": [], "changed_files": {"src/app.py"}},
    )

    adapter = adapter_module.RepoWiseAdapter()
    result = adapter.run(context)

    assert result.status is AnalyzerStatus.WARN
    assert result.score == 75.0
    assert result.findings[0].raw_impact == 2.5
    assert result.evidence[0].path == "src/app.py"
    assert result.limitations[0].kind == "missing_capability"
    assert adapter.last_report is report
