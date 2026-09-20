"""Compatibility and full health-edge registration acceptance tests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext
from repowise.core.analysis.analyzer_integration.contracts import AnalyzerResult as NewResult
from repowise.core.analysis.analyzer_integration.lifecycle import LifecycleOrchestrator
from repowise.core.analysis.analyzer_integration.registry import AnalyzerRegistry as NewRegistry

log = logging.getLogger(__name__)

EXPECTED_ANALYZER_IDS = (
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
)

_GENERIC_FAILURE_POLICY = {
    "error": "error",
    "inconclusive": "inconclusive",
    "skipped": "skipped",
}
_NATIVE_FAILURE_POLICY = {
    "fail": "fail",
    "pass": "pass",
    "skipped": "visible_skip",
    "inconclusive": "visible_inconclusive",
    "error": "visible_error",
}

# This is deliberately a complete, explicit acceptance matrix.  The registry
# only stores generic definition fields; source ownership and retry/failure/
# score policy remain at the health edge, so those contracts are listed here
# alongside the fields that can be read directly from each registered entry.
_EXPECTED_REGISTRATION_MATRIX = {
    "cicd.sourcecraft": {
        "adapter_module": "repowise.core.analysis.health.integrations.cicd_analyzer",
        "source": "sourcecraft",
        "definition": {
            "id": "cicd.sourcecraft",
            "version": "policy",
            "category": "cicd",
            "dimensions": ("delivery",),
            "requires": (),
            "supports": (),
            "phase": 60,
            "cost": 35,
            "timeout": 60.0,
            "cache_policy": "none",
            "source_commit": "sourcecraft-cicd-api",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": "delivery", "status_mapping": {}},
    },
    "chaoss.activity": {
        "adapter_module": "repowise.core.analysis.health.integrations.chaoss_adapter",
        "source": "collectoss",
        "definition": {
            "id": "chaoss.activity",
            "version": "pydriller-2.12-policy-v2",
            "category": "chaoss-activity",
            "dimensions": ("activity", "churn", "community"),
            "requires": ("chaoss:events",),
            "supports": (),
            "phase": 60,
            "cost": 35,
            "timeout": 60.0,
            "cache_policy": "read_write",
            "source_commit": "339edc520e79dd1728ca19255d94a05a4a107df1",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "chaoss.dependencies": {
        "adapter_module": "repowise.core.analysis.health.integrations.chaoss_adapter",
        "source": "collectoss",
        "definition": {
            "id": "chaoss.dependencies",
            "version": "pinned",
            "category": "chaoss-dependencies",
            "dimensions": ("dependencies", "freshness", "security"),
            "requires": ("chaoss:events",),
            "supports": (),
            "phase": 60,
            "cost": 45,
            "timeout": 60.0,
            "cache_policy": "read_write",
            "source_commit": "339edc520e79dd1728ca19255d94a05a4a107df1",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "chaoss.issues_prs": {
        "adapter_module": "repowise.core.analysis.health.integrations.chaoss_adapter",
        "source": "collectoss",
        "definition": {
            "id": "chaoss.issues_prs",
            "version": "issues-sourcecraft-policy-v1",
            "category": "chaoss-issues-prs",
            "dimensions": ("delivery", "issues", "pull_requests", "review"),
            "requires": ("chaoss:events",),
            "supports": (),
            "phase": 60,
            "cost": 40,
            "timeout": 60.0,
            "cache_policy": "read_write",
            "source_commit": "339edc520e79dd1728ca19255d94a05a4a107df1",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": "delivery", "status_mapping": {}},
    },
    "chaoss.releases": {
        "adapter_module": "repowise.core.analysis.health.integrations.chaoss_adapter",
        "source": "collectoss",
        "definition": {
            "id": "chaoss.releases",
            "version": "pinned",
            "category": "chaoss-releases",
            "dimensions": ("delivery", "releases"),
            "requires": ("chaoss:events",),
            "supports": (),
            "phase": 60,
            "cost": 30,
            "timeout": 60.0,
            "cache_policy": "read_write",
            "source_commit": "339edc520e79dd1728ca19255d94a05a4a107df1",
            "experimental": False,
            "enabled_by_mode": ("backfill", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "criticality.importance": {
        "adapter_module": "repowise.core.analysis.health.integrations.native_adapters",
        "source": "native-tools:criticality.importance",
        "definition": {
            "id": "criticality.importance",
            "version": "pinned",
            "category": "priority-context",
            "dimensions": ("blast_radius", "priority"),
            "requires": ("criticality_csv", "tool:criticality-score"),
            "supports": (),
            "phase": 40,
            "cost": 60,
            "timeout": 120.0,
            "cache_policy": "read_write",
            "source_commit": "0e76c6a99d865dddcbd89dff4117f0a54b1abfb8",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "full"),
        },
        "retry_policy": {"owner": "native-tools", "budget": 1},
        "process_policy": {"max_output_bytes": 16777216},
        "failure_policy": _NATIVE_FAILURE_POLICY,
        "score_mapping": {
            "score_dimension": None,
            "status_mapping": {"missing_signal": "inconclusive", "score_field": "priority_context"},
        },
    },
    "dependencies.enrichment": {
        "adapter_module": "repowise.core.analysis.health.integrations.dependency_adapter",
        "source": "repocrunch",
        "definition": {
            "id": "dependencies.enrichment",
            "version": "dependency-facts-v1",
            "category": "dependency-enrichment",
            "dimensions": ("dependencies", "freshness", "security"),
            "requires": ("dependency:scan",),
            "supports": (),
            "phase": 72,
            "cost": 35,
            "timeout": 60.0,
            "cache_policy": "read_write",
            "source_commit": "12938318a6bd59e30a431ab2582baff5d8673eca",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "events.temporal": {
        "adapter_module": "repowise.core.analysis.health.integrations.temporal_adapter",
        "source": "collectoss",
        "definition": {
            "id": "events.temporal",
            "version": "utc-as-of-v1",
            "category": "event-temporal-enrichment",
            "dimensions": ("activity", "churn", "community", "delivery"),
            "requires": ("chaoss:events",),
            "supports": (),
            "phase": 68,
            "cost": 20,
            "timeout": 45.0,
            "cache_policy": "read_write",
            "source_commit": "339edc520e79dd1728ca19255d94a05a4a107df1",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "forge.community": {
        "adapter_module": "repowise.core.analysis.health.integrations.forge_adapter",
        "source": "repocrunch",
        "definition": {
            "id": "forge.community",
            "version": "pinned",
            "category": "forge-community",
            "dimensions": ("community", "issues", "maintenance"),
            "requires": ("forge:github",),
            "supports": (),
            "phase": 50,
            "cost": 40,
            "timeout": 90.0,
            "cache_policy": "read_write",
            "source_commit": "12938318a6bd59e30a431ab2582baff5d8673eca",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "repocrunch", "budget": 2},
        "failure_policy": {"empty": "inconclusive", "permission_unknown": "warn", "error": "error"},
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "forge.metadata": {
        "adapter_module": "repowise.core.analysis.health.integrations.forge_adapter",
        "source": "repocrunch",
        "definition": {
            "id": "forge.metadata",
            "version": "pinned",
            "category": "forge-metadata",
            "dimensions": ("architecture", "documentation", "repository-hygiene"),
            "requires": ("forge:github",),
            "supports": (),
            "phase": 50,
            "cost": 35,
            "timeout": 90.0,
            "cache_policy": "read_write",
            "source_commit": "12938318a6bd59e30a431ab2582baff5d8673eca",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "repocrunch", "budget": 2},
        "failure_policy": {"empty": "inconclusive", "permission_unknown": "warn", "error": "error"},
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "graal.external_tools": {
        "adapter_module": "repowise.core.analysis.health.integrations.chaoss_adapter",
        "source": "graal",
        "definition": {
            "id": "graal.external_tools",
            "version": "pinned",
            "category": "external-quality-tools",
            "dimensions": ("code_quality", "dependencies", "security"),
            "requires": ("local_scan", "tool:graal"),
            "supports": (),
            "phase": 65,
            "cost": 55,
            "timeout": 120.0,
            "cache_policy": "read_write",
            "source_commit": "23ebfd0fa5249cc8e84b1992da3b26b15c0cd8f0",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "full"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "identity.enrichment": {
        "adapter_module": "repowise.core.analysis.health.integrations.identity_adapter",
        "source": "sortinghat",
        "definition": {
            "id": "identity.enrichment",
            "version": "repowise-identity-v1",
            "category": "identity-enrichment",
            "dimensions": ("community", "contributors", "ownership"),
            "requires": ("chaoss:events",),
            "supports": (),
            "phase": 70,
            "cost": 25,
            "timeout": 45.0,
            "cache_policy": "read_write",
            "source_commit": "2048a9cfb15b21da7c45082c3966a3462ce51826",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "qlty.check": {
        "adapter_module": "repowise.core.analysis.health.integrations.native_adapters",
        "source": "native-tools:qlty.check",
        "definition": {
            "id": "qlty.check",
            "version": "pinned",
            "category": "static-quality",
            "dimensions": ("code_quality", "security", "tests"),
            "requires": ("local_scan", "tool:qlty"),
            "supports": (),
            "phase": 30,
            "cost": 40,
            "timeout": 120.0,
            "cache_policy": "read_write",
            "source_commit": "338acb3405a966151cd9e29685f2a8eb71d92434",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full"),
        },
        "retry_policy": {"owner": "native-tools", "budget": 1},
        "process_policy": {"max_output_bytes": 16777216},
        "failure_policy": _NATIVE_FAILURE_POLICY,
        "score_mapping": {
            "score_dimension": None,
            "status_mapping": {"error_level": "fail", "warning_level": "warn"},
        },
    },
    "repohealth.baseline": {
        "adapter_module": "repowise.core.analysis.health.integrations.native_adapters",
        "source": "native-tools:repohealth.baseline",
        "definition": {
            "id": "repohealth.baseline",
            "version": "pinned",
            "category": "repository-hygiene",
            "dimensions": ("ci", "dependencies", "documentation", "security", "tests"),
            "requires": ("local_scan", "tool:repohealth"),
            "supports": (),
            "phase": 20,
            "cost": 25,
            "timeout": 120.0,
            "cache_policy": "read_write",
            "source_commit": "a62f96a00134e7f08541fa00dd962666222394f8",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "native-tools", "budget": 1},
        "process_policy": {"max_output_bytes": 16777216},
        "failure_policy": _NATIVE_FAILURE_POLICY,
        "score_mapping": {
            "score_dimension": "docs",
            "status_mapping": {"valid_threshold_exit": "warn"},
        },
    },
    "repowise.health": {
        "adapter_module": "repowise.core.analysis.health.integrations.repowise_adapter",
        "source": "repowise-health",
        "definition": {
            "id": "repowise.health",
            "version": "10",
            "category": "repository-health",
            "dimensions": ("defect", "maintainability", "performance"),
            "requires": ("local_scan",),
            "supports": (),
            "phase": 10,
            "cost": 20,
            "timeout": 600.0,
            "cache_policy": "none",
            "source_commit": None,
            "experimental": False,
            "enabled_by_mode": (),
        },
        "retry_policy": {"owner": "legacy-direct", "budget": 0},
        "failure_policy": {"empty": "inconclusive", "findings": "warn", "error": "error"},
        "score_mapping": {"score_dimension": None, "status_mapping": {}},
    },
    "scorecard.local": {
        "adapter_module": "repowise.core.analysis.health.integrations.native_adapters",
        "source": "native-tools:scorecard.local",
        "definition": {
            "id": "scorecard.local",
            "version": "pinned",
            "category": "security-ci",
            "dimensions": ("ci", "governance", "security"),
            "requires": ("local_scan", "tool:scorecard"),
            "supports": (),
            "phase": 30,
            "cost": 50,
            "timeout": 120.0,
            "cache_policy": "read_write",
            "source_commit": "f92023a3f77879f96e0c9c1305f289d755be4bb6",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "full"),
        },
        "retry_policy": {"owner": "native-tools", "budget": 1},
        "process_policy": {"max_output_bytes": 16777216},
        "failure_policy": _NATIVE_FAILURE_POLICY,
        "score_mapping": {
            "score_dimension": "security",
            "status_mapping": {"inconclusive_score": -1},
        },
    },
    "sokrates.analysis": {
        "adapter_module": "repowise.core.analysis.health.integrations.native_adapters",
        "source": "native-tools:sokrates.analysis",
        "definition": {
            "id": "sokrates.analysis",
            "version": "pinned",
            "category": "structural-analysis",
            "dimensions": ("churn", "code_quality", "contributors", "dependencies", "duplication"),
            "requires": ("local_scan", "tool:sokrates"),
            "supports": (),
            "phase": 35,
            "cost": 70,
            "timeout": 180.0,
            "cache_policy": "read_write",
            "source_commit": "f400eb7235a755146e854a1bf4bd90cbe1ee5086",
            "experimental": False,
            "enabled_by_mode": ("backfill", "full"),
        },
        "retry_policy": {"owner": "native-tools", "budget": 1},
        "process_policy": {"max_output_bytes": 16777216},
        "failure_policy": _NATIVE_FAILURE_POLICY,
        "score_mapping": {
            "score_dimension": None,
            "status_mapping": {"unsupported_export": "inconclusive"},
        },
    },
    "sourcecraft.appsec": {
        "adapter_module": "repowise.core.analysis.health.integrations.appsec_analyzer",
        "source": "sourcecraft-appsec",
        "definition": {
            "id": "sourcecraft.appsec",
            "version": "sourcecraft-appsec-policy-v1",
            "category": "security",
            "dimensions": ("security",),
            "requires": (),
            "supports": (),
            "phase": 60,
            "cost": 40,
            "timeout": 90.0,
            "cache_policy": "read_write",
            "source_commit": "sourcecraft-appsec-rest-v1",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": "security", "status_mapping": {}},
    },
    "vale.documentation": {
        "adapter_module": "repowise.core.analysis.health.integrations.vale_adapter",
        "source": "vale",
        "definition": {
            "id": "vale.documentation",
            "version": "policy",
            "category": "documentation-quality",
            "dimensions": ("docs",),
            "requires": ("local_scan",),
            "supports": (),
            "phase": 25,
            "cost": 30,
            "timeout": 120.0,
            "cache_policy": "read_write",
            "source_commit": "ba6a2c6a725295eb6b7698336d22dec8ffc4af1c",
            "experimental": False,
            "enabled_by_mode": ("backfill", "diff", "fast", "full", "offline"),
        },
        "retry_policy": {"owner": "lifecycle", "budget": 1},
        "failure_policy": _GENERIC_FAILURE_POLICY,
        "score_mapping": {"score_dimension": "docs", "status_mapping": {}},
    },
}


def test_old_and_new_contracts_are_identical_classes() -> None:
    from repowise.core.analysis.health.integrations.contracts import AnalyzerResult as OldResult

    assert OldResult is NewResult

    from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry as OldRegistry

    assert OldRegistry is NewRegistry


def test_neutral_registry_stays_empty_until_health_bootstrap() -> None:
    from repowise.core.analysis.health.integrations import register_all_health_adapters
    from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry as OldRegistry

    neutral = NewRegistry()
    assert neutral.ids() == ()
    health = OldRegistry()
    register_all_health_adapters(health)
    first = health.ids()
    register_all_health_adapters(health)
    assert first == EXPECTED_ANALYZER_IDS
    assert health.ids() == first
    assert all(health.get(analyzer_id) is not None for analyzer_id in first)


def test_bootstrap_registration_matrix_preserves_native_tool_metadata() -> None:
    from repowise.core.analysis.health.integrations import register_all_health_adapters
    from repowise.core.analysis.health.integrations.registry import AnalyzerRegistry as OldRegistry

    health = OldRegistry()
    register_all_health_adapters(health)
    assert tuple(sorted(_EXPECTED_REGISTRATION_MATRIX)) == EXPECTED_ANALYZER_IDS
    assert tuple(sorted(health.ids())) == EXPECTED_ANALYZER_IDS
    assert len(health.ids()) == 19

    definition_fields = (
        "id",
        "version",
        "category",
        "dimensions",
        "requires",
        "supports",
        "phase",
        "cost",
        "timeout",
        "cache_policy",
        "source_commit",
        "experimental",
        "enabled_by_mode",
    )
    for analyzer_id in EXPECTED_ANALYZER_IDS:
        entry = health.get(analyzer_id)
        assert entry is not None, analyzer_id
        definition, factory = entry
        expected = _EXPECTED_REGISTRATION_MATRIX[analyzer_id]
        actual_definition = {
            field: (
                getattr(definition, field).value
                if field == "cache_policy"
                else getattr(definition, field)
            )
            for field in definition_fields
        }
        expected_definition = dict(expected["definition"])
        if expected_definition["version"] == "policy":
            expected_prefix = {
                "vale.documentation": "vale-3.22.0-policy-v2-",
                "cicd.sourcecraft": "cicd-sourcecraft-policy-v1-",
            }[analyzer_id]
            assert definition.version.startswith(expected_prefix), analyzer_id
            expected_definition["version"] = definition.version
        assert actual_definition == expected_definition, analyzer_id
        assert factory.__module__ == expected["adapter_module"], analyzer_id
        adapter_module = factory.__module__
        if analyzer_id == "graal.external_tools":
            actual_source = "graal"
        elif adapter_module.endswith("native_adapters"):
            actual_source = f"native-tools:{analyzer_id}"
        elif adapter_module.endswith("forge_adapter"):
            actual_source = "repocrunch"
        elif adapter_module.endswith(("chaoss_adapter", "temporal_adapter")):
            actual_source = "collectoss"
        elif adapter_module.endswith("identity_adapter"):
            actual_source = "sortinghat"
        elif adapter_module.endswith("dependency_adapter"):
            actual_source = "repocrunch"
        elif adapter_module.endswith("repowise_adapter"):
            actual_source = "repowise-health"
        elif adapter_module.endswith("vale_adapter"):
            actual_source = "vale"
        elif adapter_module.endswith("cicd_analyzer"):
            actual_source = "sourcecraft"
        elif adapter_module.endswith("appsec_analyzer"):
            actual_source = "sourcecraft-appsec"
        else:
            raise AssertionError(f"unclassified adapter source for {analyzer_id}")
        assert actual_source == expected["source"], analyzer_id
        assert {
            "adapter_module",
            "source",
            "definition",
            "retry_policy",
            "failure_policy",
            "score_mapping",
        } <= set(expected), analyzer_id
        source_commits = {
            "collectoss": "339edc520e79dd1728ca19255d94a05a4a107df1",
            "sourcecraft": "sourcecraft-cicd-api",
            "sourcecraft-appsec": "sourcecraft-appsec-rest-v1",
            "graal": "23ebfd0fa5249cc8e84b1992da3b26b15c0cd8f0",
            "repocrunch": "12938318a6bd59e30a431ab2582baff5d8673eca",
            "repowise-health": None,
            "sortinghat": "2048a9cfb15b21da7c45082c3966a3462ce51826",
            "vale": "ba6a2c6a725295eb6b7698336d22dec8ffc4af1c",
        }
        if expected["source"] in source_commits:
            assert expected["definition"]["source_commit"] == source_commits[expected["source"]]

        retry_policy = expected["retry_policy"]
        assert retry_policy["budget"] >= 0, analyzer_id
        if retry_policy["owner"] == "native-tools":
            assert retry_policy["budget"] == 1, analyzer_id
        elif retry_policy["owner"] == "repocrunch":
            assert retry_policy["budget"] == 2, analyzer_id
        elif retry_policy["owner"] == "lifecycle":
            assert retry_policy["budget"] == LifecycleOrchestrator().max_retries, analyzer_id
        else:
            assert retry_policy == {"owner": "legacy-direct", "budget": 0}, analyzer_id

        failure_policy = expected["failure_policy"]
        assert failure_policy, analyzer_id
        if retry_policy["owner"] == "native-tools":
            assert failure_policy == _NATIVE_FAILURE_POLICY, analyzer_id
        elif retry_policy["owner"] != "legacy-direct":
            assert failure_policy == _GENERIC_FAILURE_POLICY or set(failure_policy) == {
                "empty",
                "permission_unknown",
                "error",
            }, analyzer_id

        score_mapping = expected["score_mapping"]
        assert set(score_mapping) == {"score_dimension", "status_mapping"}, analyzer_id
        if not expected["source"].startswith("native-tools:"):
            assert score_mapping["status_mapping"] == {}, analyzer_id

    repo_root = Path(__file__).resolve().parents[3]
    native_config = yaml.safe_load(
        (repo_root / "config" / "analyzers" / "native-tools.yaml").read_text(encoding="utf-8")
    )
    forge_config = yaml.safe_load(
        (repo_root / "config" / "analyzers" / "forge.yaml").read_text(encoding="utf-8")
    )
    assert native_config["policy"]["failure_policy"] == _NATIVE_FAILURE_POLICY
    assert native_config["policy"]["retry_budget"] == 1
    assert native_config["policy"]["cache"] == {
        "ttl_seconds": 86400,
        "stale_after_seconds": 172800,
        "allow_stale": True,
    }
    assert forge_config["forge"]["source"] == "repocrunch"
    assert forge_config["forge"]["source_commit"] == "12938318a6bd59e30a431ab2582baff5d8673eca"
    assert forge_config["forge"]["limits"]["retry_budget"] == 2

    for _analyzer_id, expected in _EXPECTED_REGISTRATION_MATRIX.items():
        source = expected["source"]
        if source.startswith("native-tools:"):
            tool = source.removeprefix("native-tools:")
            native_entry = native_config["tools"][tool]
            definition = expected["definition"]
            assert {
                "timeout",
                "max_output_bytes",
                "source_commit",
                "enabled_by_mode",
                "status_mapping",
            } <= set(native_entry), tool
            assert native_entry["timeout"] == definition["timeout"]
            assert (
                native_entry["max_output_bytes"] == expected["process_policy"]["max_output_bytes"]
            )
            assert native_entry["source_commit"] == definition["source_commit"]
            assert tuple(sorted(native_entry["enabled_by_mode"])) == definition["enabled_by_mode"]
            assert native_entry["status_mapping"] == expected["score_mapping"]["status_mapping"]
            assert expected["process_policy"] == {
                "max_output_bytes": native_entry["max_output_bytes"]
            }
        elif source == "repocrunch":
            assert expected["definition"]["source_commit"] == forge_config["forge"]["source_commit"]
            if expected["retry_policy"]["owner"] == "repocrunch":
                assert (
                    forge_config["forge"]["limits"]["retry_budget"]
                    == expected["retry_policy"]["budget"]
                )
        elif source == "collectoss":
            metrics_config = yaml.safe_load(
                (repo_root / "config" / "analyzers" / "metrics.yaml").read_text(encoding="utf-8")
            )
            assert (
                metrics_config["metrics"]["source_commit"]
                == expected["definition"]["source_commit"]
            )

    # The two registered native analyzers that expose a canonical scalar score
    # retain their legacy dimension projection; the remaining analyzers expose
    # metrics/findings only (and therefore intentionally have no score field).
    context = AnalyzerContext(
        repo_path=repo_root,
        repo_id="registration-matrix",
        head_sha="a" * 40,
        as_of_ts=datetime.now(UTC),
    )
    from repowise.core.analysis.health.integrations.native_adapters import (
        parse_repohealth,
        parse_scorecard,
    )

    assert parse_scorecard({"checks": []}, context).score_dimension == "security"
    assert parse_repohealth({"checks": [], "score": 100}, context).score_dimension == "docs"


def test_legacy_merge_is_the_neutral_merge() -> None:
    from repowise.core.analysis.analyzer_integration.finding_merge import deduplicate_findings
    from repowise.core.analysis.health.integrations.finding_merge import (
        deduplicate_findings as old_merge,
    )

    assert old_merge is deduplicate_findings
