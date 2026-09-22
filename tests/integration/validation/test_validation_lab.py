"""Safety and contract tests for the non-production validation lab."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.validation.run_repository_validation import (
    REPOSITORY_MANIFEST,
    RepositorySpec,
    clone_repository,
    collect_inventory,
    render_repository_report,
    validate_checkout,
    validate_manifest,
)
from scripts.validation.run_validation_matrix import (
    build_summary,
    classify_operational_observations,
    compare_repeat_analysis,
    detect_baseline_determinism_bugs,
    evaluate_hypotheses,
)


def _git_fixture(root: Path) -> None:
    (root / "README.md").write_text("# Fixture\n\nRun: python main.py\n", encoding="utf-8")
    (root / "main.py").write_text("# TODO: test fixture\nprint('ok')\n", encoding="utf-8")
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "validation@example.invalid"],
        ["git", "config", "user.name", "Validation"],
        ["git", "add", "."],
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "fixture"],
    ]
    for command in commands:
        subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)


def test_manifest_is_exactly_the_requested_public_matrix() -> None:
    validate_manifest()
    assert len(REPOSITORY_MANIFEST) == 13
    assert {item.slug for item in REPOSITORY_MANIFEST} == {
        "mvp-food",
        "freshly",
        "todo",
        "ocheredibm3",
        "procsima-low-version",
        "two-cucumbersfloating",
        "andromeda",
        "codeslicer",
        "repo-health-analyzer-production",
        "ruff",
        "uv",
        "fastapi",
        "pydantic",
    }
    assert all(item.url.startswith("https://github.com/") for item in REPOSITORY_MANIFEST)


def test_clone_inventory_and_production_runner_preserve_degradation(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git_fixture(source)
    monkeypatch.setenv("VALE_PATH", "missing-vale")
    monkeypatch.setenv("GIT_SIZER_PATH", "missing-git-sizer")
    fixture_token = "validation-fixture-token"
    monkeypatch.setenv("SOURCECRAFT_TOKEN", fixture_token)
    clone_spec = RepositorySpec("fixture-source", "fixture", source.as_uri(), "TEST", "fixture")
    spec = RepositorySpec("fixture", "fixture", "https://github.com/example/fixture", "TEST", "fixture")

    clone = clone_repository(clone_spec, tmp_path / "checkouts")
    assert clone.status == "cloned"
    assert clone.head_sha
    result = validate_checkout(
        spec,
        clone,
        as_of=datetime(2026, 9, 21, tzinfo=UTC),
        analysis_timeout_seconds=120,
    )

    payload = result.public_dict()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert fixture_token not in serialized
    assert result.analysis is not None
    categories = {item["category"]: item for item in result.analysis["categories"]}
    assert set(categories) == {"documentation", "activity", "issues", "cicd", "security", "code_health"}
    for name in ("issues", "cicd", "security"):
        assert categories[name]["score"] is None
        assert categories[name]["coverage"]["status"] == "unavailable"
        assert categories[name]["confidence"]["level"] == "unknown"
    assert result.timings.clone_ms >= 0
    assert result.timings.collection_ms >= 0
    assert result.timings.normalization_ms >= 0
    assert result.timings.analyzer_ms >= 0
    assert result.timings.score_engine_ms >= 0
    assert set(result.timings.source_ms) >= {
        "git",
        "git-sizer",
        "git.todo-history",
        "pydriller",
        "vale",
    }
    assert result.timings.total_ms >= result.timings.clone_ms
    assert collect_inventory(clone.checkout_path)["readme_present"] is True


def test_sonarqube_is_explicitly_opt_in_and_requires_process_secret(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git_fixture(source)
    clone_spec = RepositorySpec("fixture-source", "fixture", source.as_uri(), "TEST", "fixture")
    spec = RepositorySpec("fixture", "fixture", "https://github.com/example/fixture", "TEST", "fixture")
    clone = clone_repository(clone_spec, tmp_path / "checkouts")

    result = validate_checkout(
        spec,
        clone,
        as_of=datetime(2026, 9, 21, tzinfo=UTC),
        analysis_timeout_seconds=120,
        enable_sonarqube=True,
        sonar_url="http://127.0.0.1:9000",
        sonar_token=None,
    )

    assert result.outcome == "analysis_failed"
    assert result.errors[0]["type"] == "ValueError"
    assert "SONAR_TOKEN" in result.errors[0]["detail"]


def test_sonarqube_validation_rejects_non_local_endpoints(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git_fixture(source)
    clone_spec = RepositorySpec("fixture-source", "fixture", source.as_uri(), "TEST", "fixture")
    spec = RepositorySpec("fixture", "fixture", "https://github.com/example/fixture", "TEST", "fixture")
    clone = clone_repository(clone_spec, tmp_path / "checkouts")

    result = validate_checkout(
        spec,
        clone,
        as_of=datetime(2026, 9, 21, tzinfo=UTC),
        analysis_timeout_seconds=120,
        enable_sonarqube=True,
        sonar_url="https://sonar.example.invalid",
        sonar_token="validation-token",
    )

    assert result.outcome == "analysis_failed"
    assert "local localhost/loopback" in result.errors[0]["detail"]
    assert "validation-token" not in json.dumps(result.public_dict())


def test_report_never_converts_unavailable_to_zero() -> None:
    payload = {
        "repository": {"name": "fixture", "url": "https://github.com/example/fixture", "repository_type": "TEST"},
        "outcome": "degraded",
        "clone": {"head_sha": "a" * 40},
        "timings_ms": {"clone_ms": 1, "collection_ms": 2, "analyzer_ms": 3, "total_ms": 6},
        "capabilities": {},
        "inventory": {},
        "analysis": {
            "categories": [
                {
                    "category": "issues",
                    "status": "skipped",
                    "score": None,
                    "coverage": {"status": "unavailable"},
                    "confidence": {"level": "unknown"},
                    "source": "SourceCraft Issues",
                    "live_verified": False,
                    "evidence_count": 0,
                    "finding_count": 0,
                    "policy_version": "issues-calibration-v2",
                    "analyzer_version": "issues-v1",
                    "metrics": {},
                    "normalized_observations": [],
                    "limitations": [],
                    "formula_substitution": "not computable from available facts; score remains null",
                }
            ],
            "score": None,
            "status": {"state": "partial"},
        },
        "errors": [],
    }
    report = render_repository_report(payload)
    assert "score: **N/A**" in report
    assert "unavailable" in report
    assert "score: **0**" not in report


def test_github_sourcecraft_hypotheses_require_explicit_unavailable_semantics() -> None:
    row = {
        "repository": {"slug": "fixture", "name": "fixture"},
        "outcome": "degraded",
        "inventory": {"source_file_count": 1},
        "analysis": {
            "score": None,
            "categories": [
                {
                    "category": category,
                    "score": None,
                    "status": "skipped",
                    "coverage": {"status": "unavailable"},
                    "confidence": {"level": "unknown"},
                    "live_verified": False,
                }
                for category in ("issues", "cicd", "security")
            ],
        },
    }
    hypotheses = {item["id"]: item for item in evaluate_hypotheses([row])}
    assert hypotheses["H6"]["status"] == "PASS"
    assert hypotheses["H7"]["status"] == "PASS"
    summary = build_summary(
        [], as_of=datetime(2026, 9, 21, tzinfo=UTC), output_root=Path("artifacts/validation/test"), selected_count=1
    )
    assert summary["safe_to_proceed_to_recommendation_engine"] is False


def test_operational_observations_separate_expected_behavior_from_limitations() -> None:
    row = {
        "repository": {"slug": "fixture"},
        "capabilities": {
            "vale": {"state": "unavailable", "reason": "optional executable is unavailable"},
            "git-sizer": {"state": "unavailable", "reason": "optional executable is unavailable"},
            "sonarqube": {"state": "unavailable", "reason": "SONAR_URL is not configured"},
            "sourcecraft": {"state": "unavailable", "reason": "SOURCECRAFT_URL is not configured"},
        },
        "analysis": {
            "categories": [
                {
                    "category": "code_health",
                    "facts_available": True,
                    "score": None,
                    "status": "inconclusive",
                    "normalized_observations": [{"key": "todo_count", "value": 1}],
                }
            ]
        },
    }
    observations = classify_operational_observations([row])
    assert any(item["classification"] == "EXPECTED BEHAVIOR" for item in observations)
    assert sum(item["classification"] == "LIMITATION" for item in observations) == 4


def test_baseline_determinism_drift_is_reported_as_a_bug() -> None:
    bugs = detect_baseline_determinism_bugs(
        {
            "status": "available",
            "path": "baseline.json",
            "rows": [
                {
                    "slug": "fixture",
                    "same_head": True,
                    "category_scores": {"activity": {"before": 80.0, "after": 79.9, "delta": -0.1}},
                },
                {
                    "slug": "changed",
                    "same_head": False,
                    "category_scores": {"activity": {"before": 80.0, "after": 79.0, "delta": -1.0}},
                },
            ],
        }
    )
    assert len(bugs) == 1
    assert bugs[0]["classification"] == "BUG"
    assert bugs[0]["category"] == "activity"


def test_current_repeat_projection_is_deterministic() -> None:
    analysis = {
        "score": {"overall_score": None, "presentation_state": "INSUFFICIENT_DATA"},
        "categories": [
            {
                "category": "activity",
                "status": "pass",
                "score": 42.0,
                "metrics": {"activity_score": 42.0},
                "coverage": {"status": "complete"},
                "confidence": {"level": "high"},
                "limitations": [],
                "score_signals": {},
                "normalized_observations": [],
                "formula_substitution": "activity_score = 42.00",
            }
        ],
    }
    assert compare_repeat_analysis(analysis, analysis)["status"] == "PASS"


def test_h5_rejects_tiny_git_sizer_only_numeric_code_health() -> None:
    row = {
        "repository": {"slug": "tiny"},
        "inventory": {"source_file_count": 1},
        "analysis": {
            "categories": [
                {
                    "category": "code_health",
                    "score": 80.0,
                    "status": "warn",
                    "coverage": {"status": "partial"},
                    "confidence": {"level": "medium"},
                    "component_scores": {"git_structure": 100.0},
                }
            ]
        },
    }
    hypotheses = {item["id"]: item for item in evaluate_hypotheses([row])}
    assert hypotheses["H5"]["status"] == "ANOMALY"


def test_h5_passes_when_tiny_code_health_is_inconclusive() -> None:
    row = {
        "repository": {"slug": "tiny"},
        "inventory": {"source_file_count": 1},
        "analysis": {
            "categories": [
                {
                    "category": "code_health",
                    "score": None,
                    "status": "inconclusive",
                    "coverage": {"status": "partial"},
                    "confidence": {"level": "low"},
                    "component_scores": {},
                }
            ]
        },
    }
    hypotheses = {item["id"]: item for item in evaluate_hypotheses([row])}
    assert hypotheses["H5"]["status"] == "PASS"


def test_h3_accepts_documented_product_with_small_historical_surface() -> None:
    row = {
        "repository": {"slug": "two-cucumbersfloating"},
        "inventory": {"source_file_count": 0},
        "analysis": {
            "categories": [
                {
                    "category": "documentation",
                    "score": 81.5,
                },
                {
                    "category": "activity",
                    "metrics": {"unique_commits": 8},
                },
            ]
        },
    }
    hypotheses = {item["id"]: item for item in evaluate_hypotheses([row])}
    assert hypotheses["H3"]["status"] == "PASS"
