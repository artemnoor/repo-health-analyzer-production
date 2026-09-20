from __future__ import annotations

import subprocess
import sys

import pytest

from repowise.core.repo_health.analyzers.registry import (
    CANONICAL_ANALYZER_IDS,
    CANONICAL_SPECS,
    OWNERSHIP_MANIFEST,
    CanonicalAnalyzerRegistry,
    resolve_analyzer_id,
)

CURRENT_LEGACY_IDS = {
    "chaoss.activity",
    "chaoss.dependencies",
    "chaoss.issues_prs",
    "chaoss.releases",
    "cicd.sourcecraft",
    "criticality.importance",
    "dependencies.enrichment",
    "events.temporal",
    "forge.community",
    "forge.metadata",
    "graal.external_tools",
    "identity.enrichment",
    "qlty.check",
    "repohealth.baseline",
    "repowise.health",
    "scorecard.local",
    "sokrates.analysis",
    "sourcecraft.appsec",
    "vale.documentation",
}


def test_canonical_registry_contains_exactly_six_unique_categories() -> None:
    registry = CanonicalAnalyzerRegistry(CANONICAL_SPECS)

    registry.validate()

    assert registry.ids() == tuple(sorted(CANONICAL_ANALYZER_IDS))
    assert len({spec.category for spec in registry.definitions()}) == 6
    assert all(spec.public_result == "CategoryResult" for spec in registry.definitions())


def test_ownership_manifest_classifies_every_current_legacy_id_once() -> None:
    records = {item.current_id: item for item in OWNERSHIP_MANIFEST}
    assert CURRENT_LEGACY_IDS.issubset(records)
    assert len(records) == len(OWNERSHIP_MANIFEST)
    assert {item.canonical_id for item in records.values()} == set(CANONICAL_ANALYZER_IDS)
    assert all(item.category.value in item.input_fact_group or item.input_fact_group for item in records.values())

    vale = resolve_analyzer_id("vale.documentation")
    assert vale.kind == "alias"
    assert vale.canonical_id == "repo-health.documentation"

    scorecard = resolve_analyzer_id("scorecard.local")
    assert scorecard.kind == "auxiliary"
    assert scorecard.canonical_id == "repo-health.security"


def test_canonical_specs_have_stable_serialized_metadata() -> None:
    first = [spec.model_dump(mode="json") for spec in CANONICAL_SPECS]
    spec_type = type(CANONICAL_SPECS[0])
    second = [spec_type.model_validate(item).model_dump(mode="json") for item in reversed(first)]

    assert sorted(first, key=lambda item: item["id"]) == sorted(second, key=lambda item: item["id"])
    assert all("repo_path" not in spec.model_dump_json() for spec in CANONICAL_SPECS)


def test_registry_rejects_duplicate_specs_and_unregistered_factories() -> None:
    registry = CanonicalAnalyzerRegistry(CANONICAL_SPECS)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_spec(CANONICAL_SPECS[0])
    with pytest.raises(KeyError, match="unknown canonical"):
        registry.register_factory("vale.documentation", lambda _: None)  # type: ignore[arg-type]


def test_importing_canonical_analyzer_package_has_no_legacy_registration_side_effect() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import repowise.core.repo_health.analyzers; "
                "print(any(name.startswith('repowise.core.analysis.health.integrations') "
                "for name in sys.modules))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "False"
