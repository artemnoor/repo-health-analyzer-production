import json
from datetime import UTC, datetime
from pathlib import Path

from repowise.core.analysis.health.integrations.contracts import AnalyzerContext, AnalyzerStatus
from repowise.core.analysis.health.integrations.dependency_adapter import (
    DependencyAdapter,
    dependency_edges,
    parse_dependency_facts,
)

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _context(inventory: dict) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=Path("."),
        repo_id="sample",
        head_sha="c" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["dependency:scan"],
        inventory=inventory,
    )


def test_copied_repocrunch_parsers_classify_direct_and_dev_dependencies() -> None:
    manifests = json.loads((FIXTURES / "dependencies" / "manifests.json").read_text(encoding="utf-8"))
    context = _context({**manifests, "lockfiles": ["poetry.lock", "pnpm-lock.yaml"], "repository_files": ["poetry.lock", "pnpm-lock.yaml"]})
    facts = parse_dependency_facts(context)
    kinds = {(fact.name, fact.kind) for fact in facts}

    assert ("requests", "direct") in kinds
    assert ("pytest", "dev") in kinds
    assert ("react", "direct") in kinds
    assert ("vitest", "dev") in kinds
    assert all(fact.source_event_ids for fact in facts)


def test_rows_preserve_lockfile_sbom_libyear_and_vulnerability_provenance() -> None:
    context = _context({
        "dependency_rows": [
            {"name": "openssl", "manifest_path": "Cargo.toml", "package_manager": "cargo", "kind": "runtime", "version": "1.2", "lockfile": "Cargo.lock", "sbom_ref": "sbom://1", "libyear": 2.5, "vulnerabilities": ["CVE-2026-1"], "source_event_id": "dep-1"}
        ],
        "dependency_edges": [
            {"source_path": "src/main.rs", "target": "openssl", "type": "path-name", "fragment": "use openssl::ssl", "source_event_id": "edge-1"}
        ],
    })
    result = DependencyAdapter().result(context)
    edges = dependency_edges(context)

    fact = parse_dependency_facts(context)[0]
    assert fact.kind == "runtime"
    assert fact.lockfile == "Cargo.lock"
    assert fact.sbom_ref == "sbom://1"
    assert fact.libyear == 2.5
    assert fact.vulnerability_refs == ("CVE-2026-1",)
    assert result.status is AnalyzerStatus.WARN
    assert edges[0].confidence == 0.6
    assert edges[0].evidence_fragment == "use openssl::ssl"


def test_dependency_cycles_are_visible() -> None:
    context = _context({"dependency_edges": [{"source_path": "a", "target": "b", "edge_type": "ast"}, {"source_path": "b", "target": "a", "edge_type": "ast"}]})
    result = DependencyAdapter().result(context)
    assert result.diagnostics["cycle_count"] == 1
    assert any("cycle" in finding.reason for finding in result.findings)
