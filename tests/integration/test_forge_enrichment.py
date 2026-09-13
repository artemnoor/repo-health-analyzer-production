import json
from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.chaoss_adapter import (
    CHAOSS_DEPENDENCIES_ID,
    CHAOSS_ISSUES_PRS_ID,
    ChaossAdapter,
)
from repowise.core.analysis.health.integrations.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.dependency_adapter import DependencyAdapter
from repowise.core.analysis.health.integrations.forge_adapter import ForgeAdapter
from repowise.core.analysis.health.integrations.identity_adapter import IdentityAdapter
from repowise.core.analysis.health.integrations.temporal_adapter import TemporalAdapter


def test_forge_and_chaoss_fixture_enrichment_replays_into_one_envelope() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures"
    forge_payload = json.loads((fixtures / "forge" / "repocrunch.json").read_text(encoding="utf-8"))
    chaoss_rows = json.loads((fixtures / "chaoss" / "rows.json").read_text(encoding="utf-8"))
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id="acme/sample",
        head_sha="e" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["forge:github", "chaoss:events"],
        inventory={"forge_payload": forge_payload, "chaoss_rows": chaoss_rows, "metric_window": "30d"},
    )

    forge = ForgeAdapter().result(context, focus="community")
    chaoss = ChaossAdapter().result(context, analyzer_id=CHAOSS_ISSUES_PRS_ID)
    dependencies = ChaossAdapter().result(context, analyzer_id=CHAOSS_DEPENDENCIES_ID)

    assert forge.status is AnalyzerStatus.PASS
    assert chaoss.status is AnalyzerStatus.PASS
    assert dependencies.status is AnalyzerStatus.PASS
    assert any(metric.name == "chaoss:pull_requests_new" for metric in chaoss.metrics)
    assert any(metric.name == "chaoss:deps" for metric in dependencies.metrics)
    assert all(fact.source == "collectoss" for fact in ChaossAdapter().collect(context))


def test_forge_events_replay_through_identity_temporal_and_dependency_layers() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures"
    forge_payload = json.loads((fixtures / "forge" / "repocrunch.json").read_text(encoding="utf-8"))
    contributors = json.loads((fixtures / "identity" / "contributors.json").read_text(encoding="utf-8"))
    dependency_payload = json.loads((fixtures / "dependencies" / "manifests.json").read_text(encoding="utf-8"))
    context = AnalyzerContext(
        repo_path=Path("."),
        repo_id="acme/sample",
        head_sha="f" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["forge:github", "chaoss:events", "dependency:scan"],
        inventory={
            "forge_payload": forge_payload,
            **contributors,
            **dependency_payload,
            "dependency_edges": [{"source_path": "src/app.py", "target": "requests", "edge_type": "heuristic", "evidence_fragment": "import requests"}],
            "metric_window": "30d",
        },
    )

    identity = IdentityAdapter().result(context)
    temporal = TemporalAdapter().result(context)
    dependencies = DependencyAdapter().result(context)

    assert identity.diagnostics["immutable_raw"] is True
    assert temporal.diagnostics["normalization_policy"] == "utc-as-of-v1"
    assert any(metric.name == "dependencies:direct" for metric in dependencies.metrics)
    assert any(finding.dimension == "dependencies" for finding in dependencies.findings)
