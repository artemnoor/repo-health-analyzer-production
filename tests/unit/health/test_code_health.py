"""Unit and composition tests for the normalized Code Health boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    MetricValue,
)
from repowise.core.analysis.analyzer_integration.process import ProcessOutput
from repowise.core.analysis.health.integrations.code_health_analyzer import CodeHealthAnalyzer
from repowise.core.analysis.health.integrations.code_health_collector import (
    CodeHealthFactsCollector,
    CodeHealthSourcePorts,
)
from repowise.core.analysis.health.integrations.code_health_facts import (
    CodeHealthPolicy,
    CodeHealthStatus,
)
from repowise.core.analysis.health.integrations.git_sizer_adapter import GitSizerAdapter
from repowise.core.analysis.health.integrations.sonarqube_adapter import SonarQubeAdapter
from repowise.core.analysis.health.integrations.todo_debt_adapter import TodoDebtAdapter


def _context(tmp_path: Path, **inventory: object) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=tmp_path,
        repo_id="fixture",
        head_sha="abc123",
        as_of_ts=datetime(2026, 9, 19, tzinfo=UTC),
        mode="full",
        inventory=dict(inventory),
    )


def _sonar_snapshot() -> dict[str, object]:
    return {
        "schema_version": "repowise-sonarqube-code-health-v1",
        "status": "SUCCESS",
        "project_key": "fixture",
        "server_version": "Community Build",
        "measures": {
            "sqale_rating": {"value": "2"},
            "sqale_index": {"value": "90"},
            "code_smells": {"value": "4"},
            "cognitive_complexity": {"value": "15"},
            "complexity": {"value": "8"},
            "duplicated_lines_density": {"value": "2.5"},
            "ncloc": {"value": "1000"},
            "coverage": {"value": "88.0"},
        },
        "coverage_provenance": {"report_path": "coverage.xml", "report_type": "xml"},
        "components": [
            {"path": "src/main.py", "measures": [{"metric": "code_smells", "value": "2"}]},
        ],
        "issues": [
            {"key": "smell-1", "type": "CODE_SMELL", "rule": "python:S100", "severity": "MAJOR", "component": "fixture:src/main.py", "line": 12, "message": "Use a descriptive name"},
            {"key": "bug-1", "type": "BUG", "rule": "python:S1192", "severity": "MINOR", "component": "fixture:src/main.py", "line": 20, "effort": "5", "message": "Duplicated literal"},
            {"key": "security-1", "type": "VULNERABILITY", "severity": "CRITICAL", "component": "fixture:src/main.py", "line": 30},
        ],
    }


def _git_snapshot() -> dict[str, object]:
    return {
        "json_version": "2",
        "tool_version": "git-sizer 1.5",
        "uniqueRefCount": {"value": 7, "levelOfConcern": "low"},
        "uniqueCommitCount": {"value": 13},
        "maxBlobSize": {"value": 4757, "objectPath": "README.md", "levelOfConcern": "none"},
        "maxPathDepth": {"value": 2, "levelOfConcern": "none"},
        "maxCheckoutSize": {"value": 9247},
    }


def _todo_snapshot() -> dict[str, object]:
    return {
        "status": "MEASURED",
        "included_loc": 1000,
        "source_files": 4,
        "hotspot_count": 1,
        "todos": [
            {"marker": "TODO", "path": "src/main.py", "line": 10, "age_days": 365, "blame_commit": "deadbeef"},
            {"marker": "FIXME", "path": "src/other.py", "line": 4, "age_days": 10},
            {"marker": "TODO", "path": "vendor/lib.py", "line": 1, "age_days": 900},
        ],
    }


def test_sonarqube_adapter_normalizes_metrics_components_and_excludes_security(tmp_path: Path) -> None:
    context = _context(tmp_path)
    facts = SonarQubeAdapter().collect(context, CodeHealthPolicy(root=tmp_path), snapshot=_sonar_snapshot())

    assert facts.status is CodeHealthStatus.MEASURED
    assert facts.measures["maintainability_rating"] == 2.0
    assert facts.measures["technical_debt_minutes"] == 90.0
    assert facts.measures["ncloc"] == 1000.0
    assert facts.coverage_status is CodeHealthStatus.MEASURED
    assert len(facts.issues) == 2
    assert facts.diagnostics["ignored_security_issue_count"] == 1
    assert facts.components[0]["path"] == "src/main.py"


def test_sonarqube_adapter_distinguishes_malformed_and_missing_coverage(tmp_path: Path) -> None:
    context = _context(tmp_path)
    adapter = SonarQubeAdapter()
    malformed = adapter.collect(context, CodeHealthPolicy(root=tmp_path), snapshot="not-json")
    no_coverage = adapter.collect(context, CodeHealthPolicy(root=tmp_path), snapshot={"measures": {"coverage": "88"}})

    assert malformed.status is CodeHealthStatus.ERROR
    assert no_coverage.coverage_status is CodeHealthStatus.NOT_APPLICABLE
    assert "coverage" not in no_coverage.measures


def test_redacted_live_sonarqube_contract_fixture_is_usable(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    snapshot = json.loads((root / "tests/fixtures/code_health/sonarqube_api.json").read_text(encoding="utf-8"))
    facts = SonarQubeAdapter().collect(_context(tmp_path), CodeHealthPolicy(root=tmp_path), snapshot=snapshot)

    assert facts.server_version == "26.9.0.129388"
    assert facts.issues[0].effort_minutes == 6.0
    assert facts.measures["remediation_effort"] == 6.0
    assert facts.coverage_status is CodeHealthStatus.NOT_APPLICABLE
    assert "coverage" not in facts.measures


def test_git_sizer_adapter_parses_json_v2_and_missing_binary(tmp_path: Path) -> None:
    context = _context(tmp_path)
    policy = CodeHealthPolicy(root=tmp_path)
    measured = GitSizerAdapter().collect(context, policy, snapshot=_git_snapshot())
    unavailable = GitSizerAdapter().collect(context, policy)

    assert measured.status is CodeHealthStatus.MEASURED
    assert measured.metrics["unique_commit_count"] == 13
    assert measured.metrics["max_blob_size"] == 4757
    assert measured.evidence[0].source == "git-sizer"
    assert unavailable.status is CodeHealthStatus.UNAVAILABLE

    real_snapshot = json.loads(
        (Path(__file__).resolve().parents[3] / "spikes/code_health/git-sizer/runs/fixture.json").read_text(encoding="utf-8")
    )
    real_facts = GitSizerAdapter().collect(context, policy, snapshot=real_snapshot)
    assert real_facts.metrics["unique_ref_count"] == 7
    assert real_facts.metrics["max_path_depth"] == 2


def test_git_sizer_adapter_distinguishes_timeout_and_malformed_json(tmp_path: Path) -> None:
    class TimedOutProcess:
        def run(self, _request: object) -> ProcessOutput:
            return ProcessOutput("code-health.git-sizer", None, json.dumps(_git_snapshot()), "timeout", 10, timed_out=True)

    context = _context(tmp_path, code_health_enabled=True).model_copy(update={"tool_paths": {"git-sizer": "git-sizer"}})
    policy = CodeHealthPolicy(root=tmp_path)
    timed_out = GitSizerAdapter().collect(context, policy, runner=TimedOutProcess())
    malformed = GitSizerAdapter().collect(context, policy, snapshot="{broken")

    assert timed_out.status is CodeHealthStatus.ERROR
    assert timed_out.timed_out is True
    assert malformed.status is CodeHealthStatus.ERROR


def test_todo_adapter_applies_exclusions_and_old_age_policy(tmp_path: Path) -> None:
    context = _context(tmp_path)
    facts = TodoDebtAdapter().collect(context, CodeHealthPolicy(root=tmp_path), snapshot=_todo_snapshot())

    assert facts.status is CodeHealthStatus.MEASURED
    assert facts.todo_count == 1
    assert facts.fixme_count == 1
    assert facts.old_count == 1
    assert facts.included_loc == 1000
    assert all(item.path != "vendor/lib.py" for item in facts.facts)


def test_todo_source_map_excludes_generated_and_minified_files(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        code_health_source_map={
            "src/main.py": "# TODO\nvalue = 1\n",
            "generated/client.py": "# TODO\n",
            "web/bundle.min.js": "// FIXME\n",
        },
    )
    facts = TodoDebtAdapter().collect(context, CodeHealthPolicy(root=tmp_path))

    assert facts.todo_count == 1
    assert facts.fixme_count == 0
    assert facts.excluded_files == 2


def test_todo_adapter_reuses_git_meta_blame_and_hotspot_data(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text("# TODO: remove this\nvalue = 1\n", encoding="utf-8")
    authored_at = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    blame_index = SimpleNamespace(lines={1: ("deadbeef", int(authored_at))})
    context = _context(
        tmp_path,
        git_meta_map={"src/main.py": {"is_hotspot": True, "blame_index": blame_index}},
    )

    facts = TodoDebtAdapter().collect(context, CodeHealthPolicy(root=tmp_path))

    assert facts.status is CodeHealthStatus.MEASURED
    assert facts.diagnostics["source"] == "git_meta_map"
    assert facts.diagnostics["age_available"] is True
    assert facts.hotspot_count == 1
    assert facts.todo_count == 1
    assert facts.facts[0].blame_commit == "deadbeef"
    assert facts.facts[0].age_days is not None and facts.facts[0].age_days > 500


def test_collector_and_analyzer_are_deterministic_and_do_not_double_count(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        sonarqube_code_health=_sonar_snapshot(),
        git_sizer=_git_snapshot(),
        git_history_code_health=_todo_snapshot(),
    )
    baseline = AnalyzerResult(
        analyzer_id="repowise.health",
        analyzer_version="baseline",
        status=AnalyzerStatus.PASS,
        score=75.0,
        metrics=(MetricValue(name="file_health:src/main.py", dimension="code", value=7.5, unit="score_0_10", score=75.0),),
    )
    collector = CodeHealthFactsCollector()
    facts_a = collector.collect(context, baseline)
    facts_b = collector.collect(context, baseline)
    result_a = CodeHealthAnalyzer().analyze(context, facts_a, baseline)
    result_b = CodeHealthAnalyzer().analyze(context, facts_b, baseline)

    assert facts_a.summary() == facts_b.summary()
    assert result_a.score == result_b.score
    assert result_a.score is not None
    assert result_a.diagnostics["double_counting_guard"] == "observation_metrics_only_aggregate_score"
    assert all(metric.score is None for metric in result_a.metrics)
    assert result_a.diagnostics["code_health_score_before"] == 75.0


def test_missing_sonar_uses_available_components_and_partial_cap(tmp_path: Path) -> None:
    context = _context(tmp_path, code_health_enabled=True, code_health_source_map={"src/main.py": "# TODO\nvalue = 1\n"})
    baseline = AnalyzerResult(
        analyzer_id="repowise.health",
        analyzer_version="baseline",
        status=AnalyzerStatus.PASS,
        score=81.0,
        metrics=(MetricValue(name="file_health:src/main.py", dimension="code", value=8.1, unit="score_0_10", score=81.0),),
    )
    facts = CodeHealthFactsCollector().collect(context, baseline, source_ports=CodeHealthSourcePorts())
    result = CodeHealthAnalyzer().analyze(context, facts, baseline)

    assert facts.sonar is not None and facts.sonar.status is CodeHealthStatus.UNAVAILABLE
    assert result.score == 0.0
    assert result.diagnostics["code_health_score_before"] == 81.0
    assert result.diagnostics["code_health_score_after"] == 0.0
    assert result.diagnostics["code_health_eligible_weight"] > 0.0
    assert result.diagnostics["code_health"]["engine_statuses"]["sonarqube"] == "UNAVAILABLE"
    assert all(metric.score is None for metric in result.metrics)


def test_repowise_adapter_enriches_existing_result_without_new_registry_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import repowise.core.analysis.health.integrations.repowise_adapter as adapter_module
    from repowise.core.analysis.health.models import HealthFileMetricData, HealthReport

    report = HealthReport(
        repo_id="fixture",
        analyzed_at=datetime(2026, 9, 19, tzinfo=UTC),
        metrics=[HealthFileMetricData(file_path="src/main.py", score=7.5, max_ccn=2, max_nesting=1, nloc=100, has_test_file=False)],
        kpis={"average_health": 7.5},
    )

    class FakeHealthAnalyzer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def analyze(self, *_args: object, **_kwargs: object) -> HealthReport:
            return report

    monkeypatch.setattr(adapter_module, "HealthAnalyzer", FakeHealthAnalyzer)
    captured: dict[str, object] = {}
    original_collect = adapter_module.CodeHealthFactsCollector.collect

    def capture_code_health_context(self: object, code_health_context: AnalyzerContext, *args: object, **kwargs: object):
        captured["git_meta_map"] = code_health_context.inventory.get("git_meta_map")
        return original_collect(self, code_health_context, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(adapter_module.CodeHealthFactsCollector, "collect", capture_code_health_context)
    git_meta_map = {"src/main.py": {"is_hotspot": True}}
    context = _context(
        tmp_path,
        graph=None,
        parsed_files=[],
        code_health_enabled=True,
        sonarqube_code_health=_sonar_snapshot(),
        git_sizer=_git_snapshot(),
        git_history_code_health=_todo_snapshot(),
        git_meta_map=git_meta_map,
    )

    result = adapter_module.RepoWiseAdapter().run(context)

    assert result.analyzer_id == "repowise.health"
    assert result.score is not None
    assert result.diagnostics["double_counting_guard"] == "observation_metrics_only_aggregate_score"
    assert result.diagnostics["code_health"]["engine_statuses"]["sonarqube"] == "MEASURED"
    assert all(metric.score is None for metric in result.metrics)
    enriched_map = captured["git_meta_map"]
    assert isinstance(enriched_map, dict)
    assert enriched_map["src/main.py"]["is_hotspot"] is True
