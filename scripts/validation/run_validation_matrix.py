"""Run the reproducible GitHub validation matrix and build evidence reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import structlog

try:
    from .run_repository_validation import (
        REPOSITORY_MANIFEST,
        ValidationRunResult,
        _configure_logging,
        _fmt,
        _fmt_ratio,
        _parse_as_of,
        clone_repository,
        default_checkout_root,
        validate_checkout,
        validate_manifest,
        write_result,
    )
except ImportError:
    from run_repository_validation import (
        REPOSITORY_MANIFEST,
        ValidationRunResult,
        _configure_logging,
        _fmt,
        _fmt_ratio,
        _parse_as_of,
        clone_repository,
        default_checkout_root,
        validate_checkout,
        validate_manifest,
        write_result,
    )

log = structlog.get_logger("repo_health.validation.matrix")

MANUAL_DEEP_DIVE_SLUGS = ("mvp-food", "todo", "two-cucumbersfloating", "andromeda", "ruff")
_SOURCECRAFT_CATEGORIES = ("issues", "cicd", "security")
DEFAULT_BASELINE_SUMMARY = Path("artifacts/validation/20260921T193407Z-420d811d/summary.json")


def run_matrix(
    *,
    output_root: Path,
    checkout_root: Path,
    as_of: datetime,
    selected_slugs: set[str] | None = None,
    clone_timeout_seconds: float = 600.0,
    analysis_timeout_seconds: float = 900.0,
    enable_sonarqube: bool = False,
    sonar_url: str | None = None,
    sonar_token: str | None = None,
    baseline_summary_path: Path | None = None,
) -> dict[str, object]:
    validate_manifest()
    selected = tuple(item for item in REPOSITORY_MANIFEST if not selected_slugs or item.slug in selected_slugs)
    unknown = sorted((selected_slugs or set()) - {item.slug for item in REPOSITORY_MANIFEST})
    if unknown:
        raise ValueError(f"unknown repository slugs: {', '.join(unknown)}")
    output_root.mkdir(parents=True, exist_ok=True)
    checkout_root.mkdir(parents=True, exist_ok=True)
    log.info(
        "validation_matrix_started",
        repository_count=len(selected),
        as_of=as_of.isoformat(),
        output_root=str(output_root),
    )
    results: list[ValidationRunResult] = []
    for spec in selected:
        clone = clone_repository(spec, checkout_root, timeout_seconds=clone_timeout_seconds)
        result = validate_checkout(
            spec,
            clone,
            as_of=as_of,
            analysis_timeout_seconds=analysis_timeout_seconds,
            enable_sonarqube=enable_sonarqube,
            sonar_url=sonar_url,
            sonar_token=sonar_token,
        )
        if result.outcome != "clone_failed" and clone.checkout_path is not None:
            repeat = validate_checkout(
                spec,
                clone,
                as_of=as_of,
                analysis_timeout_seconds=analysis_timeout_seconds,
                enable_sonarqube=enable_sonarqube,
                sonar_url=sonar_url,
                sonar_token=sonar_token,
            )
            result.determinism = compare_repeat_analysis(result.analysis, repeat.analysis)
        write_result(result, output_root)
        results.append(result)
        log.info(
            "validation_repository_completed",
            slug=spec.slug,
            outcome=result.outcome,
            clone_ms=result.timings.clone_ms,
            collection_ms=result.timings.collection_ms,
            normalization_ms=result.timings.normalization_ms,
            analyzer_ms=result.timings.analyzer_ms,
            score_engine_ms=result.timings.score_engine_ms,
            total_ms=result.timings.total_ms,
        )
    summary = build_summary(
        results,
        as_of=as_of,
        output_root=output_root,
        selected_count=len(selected),
        baseline_summary_path=baseline_summary_path,
    )
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary_path = output_root / "summary.md"
    summary_path.write_text(render_summary_markdown(summary), encoding="utf-8")
    log.info(
        "validation_matrix_finished",
        repository_count=len(selected),
        engine_validation_status=summary["engine_validation_status"],
        bug_count=len(summary["actual_bugs"]),
        outlier_count=len(summary["outliers"]),
    )
    return summary


def compare_repeat_analysis(
    first: Mapping[str, object] | None, second: Mapping[str, object] | None
) -> dict[str, object]:
    """Compare scoring projections while ignoring audit timestamps and IDs."""

    if not isinstance(first, Mapping) or not isinstance(second, Mapping):
        return {"status": "NOT_TESTABLE", "mismatches": ["analysis unavailable"]}
    first_projection = _stable_analysis_projection(first)
    second_projection = _stable_analysis_projection(second)
    if first_projection == second_projection:
        return {"status": "PASS", "mismatches": []}
    return {
        "status": "FAIL",
        "mismatches": _projection_mismatches(first_projection, second_projection),
    }


def _stable_analysis_projection(analysis: Mapping[str, object]) -> dict[str, object]:
    categories = []
    raw_categories = analysis.get("categories", [])
    for category in raw_categories if isinstance(raw_categories, list) else []:
        if not isinstance(category, Mapping):
            continue
        categories.append(
            {
                key: category.get(key)
                for key in (
                    "category",
                    "status",
                    "score",
                    "metrics",
                    "coverage",
                    "confidence",
                    "limitations",
                    "score_signals",
                    "normalized_observations",
                    "formula_substitution",
                )
            }
        )
    score = analysis.get("score")
    score_projection = None
    if isinstance(score, Mapping):
        score_projection = {
            key: score.get(key)
            for key in (
                "overall_score",
                "score_before_caps",
                "presentation_state",
                "coverage",
                "confidence",
                "score_status",
                "applied_caps",
            )
        }
    return {"score": score_projection, "categories": sorted(categories, key=lambda item: str(item["category"]))}


def _projection_mismatches(first: Mapping[str, object], second: Mapping[str, object]) -> list[str]:
    mismatches = []
    if first.get("score") != second.get("score"):
        mismatches.append("score projection differs")
    first_categories = first.get("categories", [])
    second_categories = second.get("categories", [])
    if first_categories != second_categories:
        mismatches.append("category scoring projection differs")
    return mismatches or ["stable projection differs"]


def build_summary(
    results: list[ValidationRunResult],
    *,
    as_of: datetime,
    output_root: Path,
    selected_count: int,
    baseline_summary_path: Path | None = None,
) -> dict[str, object]:
    rows = [result.public_dict() for result in results]
    hypotheses = evaluate_hypotheses(rows)
    outliers = detect_outliers(rows)
    operational_observations = classify_operational_observations(rows)
    hypothesis_anomalies = [item for item in hypotheses if item.get("status") == "ANOMALY"]
    baseline_comparison = compare_with_baseline(rows, baseline_summary_path)
    historical_determinism_observations = detect_baseline_determinism_bugs(baseline_comparison)
    determinism_bugs = [
        {
            "repository": row["repository"]["slug"],
            "category": "matrix",
            "observed": row.get("determinism"),
            "expected_relationship": "same checkout plus same as_of must produce the same scoring projection",
            "evidence": row.get("determinism"),
            "possible_cause": "repeated validation projections differ",
            "classification": "BUG",
        }
        for row in rows
        if isinstance(row.get("determinism"), Mapping) and row["determinism"].get("status") == "FAIL"
    ]
    classifications = {
        "actual_bugs": [
            *[item for item in outliers if item["classification"] == "BUG"],
            *determinism_bugs,
        ],
        "calibration_questions": [
            *[item for item in outliers if item["classification"] == "CALIBRATION QUESTION"],
            *hypothesis_anomalies,
        ],
        "hypothesis_anomalies": hypothesis_anomalies,
        "expected_behavior": [
            item for item in (*outliers, *operational_observations) if item["classification"] == "EXPECTED BEHAVIOR"
        ],
        "limitations": [
            item for item in (*outliers, *operational_observations) if item["classification"] == "LIMITATION"
        ],
    }
    clone_failures = sum(item["outcome"] == "clone_failed" for item in rows)
    analysis_failures = sum(item["outcome"] == "analysis_failed" for item in rows)
    sourcecraft_live = all(
        bool(_category(row, category) and _category(row, category).get("live_verified"))
        for row in rows
        for category in _SOURCECRAFT_CATEGORIES
        if row.get("analysis") is not None
    )
    engine_status = (
        "FAIL — BUG"
        if classifications["actual_bugs"] or analysis_failures
        else "FAIL — CALIBRATION"
        if classifications["calibration_questions"]
        else "PASS WITH EXTERNAL COVERAGE LIMITATIONS"
        if clone_failures or classifications["limitations"]
        else "PASS"
    )
    complete_matrix = selected_count == len(REPOSITORY_MANIFEST) and len(rows) == len(REPOSITORY_MANIFEST)
    safe_to_proceed = (
        complete_matrix
        and not classifications["actual_bugs"]
        and not classifications["calibration_questions"]
        and not analysis_failures
        and not clone_failures
    )
    manual = []
    for slug in MANUAL_DEEP_DIVE_SLUGS:
        row = next((item for item in rows if item["repository"]["slug"] == slug), None)
        if row is None:
            manual.append({"slug": slug, "status": "NOT_RUN"})
            continue
        manual.append(_manual_deep_dive(row, output_root))
    capabilities = next((row.get("capabilities", {}) for row in rows if row.get("capabilities")), {})
    pinned_tools = _load_pinned_tools()
    return {
        "schema_version": "repo-health-validation-summary-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "artifact_root": str(output_root).replace("\\", "/"),
        "repository_count": selected_count,
        "repositories": rows,
        "comparison": comparison_rows(rows),
        "baseline_comparison": baseline_comparison,
        "hypotheses": hypotheses,
        "outliers": outliers,
        **classifications,
        "historical_baseline_determinism_observations": historical_determinism_observations,
        "manual_deep_dives": manual,
        "performance": [
            {
                "slug": row["repository"]["slug"],
                "type": row["repository"]["repository_type"],
                **row["timings_ms"],
            }
            for row in rows
        ],
        "environment": {
            "capabilities": capabilities,
            "pinned_tools": pinned_tools,
            "adapter_notes": [
                "Vale adapter now parses the official file-keyed JSON shape and passes the validation config explicitly; scoring semantics are unchanged.",
                "Activity determinism, documentation evidence, Code Health partial semantics, and production source-scope fixes are included; Score Engine v1 weights remain unchanged.",
            ],
            "sourcecraft_categories_live_verified": sourcecraft_live,
            "sourcecraft_note": "GitHub-only validation never substitutes GitHub Issues or Actions; Security remains SourceCraft AppSec-only. Production Issues/CI/CD providers are exercised only by controlled SourceCraft runs.",
            "baseline_summary": str(baseline_summary_path).replace("\\", "/") if baseline_summary_path else None,
        },
        "engine_validation_status": engine_status,
        "safe_to_proceed_to_recommendation_engine": safe_to_proceed,
        "safe_to_proceed_reason": _recommendation_gate_reason(
            safe_to_proceed=safe_to_proceed,
            complete_matrix=complete_matrix,
            actual_bugs=classifications["actual_bugs"],
            calibration_questions=classifications["calibration_questions"],
            analysis_failures=analysis_failures,
            clone_failures=clone_failures,
            sourcecraft_live=sourcecraft_live,
        ),
    }


def _load_pinned_tools() -> dict[str, object]:
    path = Path(__file__).resolve().parent / "tool-versions.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unavailable"}
    return value if isinstance(value, dict) else {"status": "invalid"}


def detect_baseline_determinism_bugs(value: Mapping[str, object]) -> list[dict[str, object]]:
    """Flag material same-HEAD Activity drift without changing production behavior."""

    if value.get("status") != "available":
        return []
    examples = []
    for row in value.get("rows", []) if isinstance(value.get("rows"), list) else []:
        if not isinstance(row, Mapping) or row.get("same_head") is not True:
            continue
        scores = row.get("category_scores")
        activity = scores.get("activity") if isinstance(scores, Mapping) else None
        delta = activity.get("delta") if isinstance(activity, Mapping) else None
        if isinstance(delta, (int, float)) and abs(delta) > 0.01:
            examples.append(
                {
                    "slug": row.get("slug"),
                    "delta": delta,
                    "before": activity.get("before"),
                    "after": activity.get("after"),
                }
            )
    if not examples:
        return []
    return [
        {
            "repository": "matrix",
            "category": "activity",
            "classification": "BUG",
            "observed": examples,
            "expected_relationship": "same immutable HEAD and same as_of must produce deterministic Activity score",
            "evidence": {
                "same_head_examples": examples,
                "baseline": value.get("path"),
            },
            "possible_cause": "Activity recency currently references wall-clock RepositoryFacts.collected_at instead of the fixed AnalysisRequest.as_of; do not auto-fix during validation.",
        }
    ]


def _recommendation_gate_reason(
    *,
    safe_to_proceed: bool,
    complete_matrix: bool,
    actual_bugs: list[object],
    calibration_questions: list[object],
    analysis_failures: int,
    clone_failures: int,
    sourcecraft_live: bool,
) -> str:
    if safe_to_proceed:
        return "All 13 repositories completed without runner/data bugs, calibration questions, analysis failures, or clone failures. SourceCraft AppSec live coverage remains an explicit external follow-up if credentials are unavailable."
    blockers = []
    if not complete_matrix:
        blockers.append("the complete 13-repository matrix did not finish")
    if actual_bugs:
        blockers.append(f"{len(actual_bugs)} actual bug classification(s)")
    if calibration_questions:
        blockers.append(f"{len(calibration_questions)} calibration question(s)")
    if analysis_failures:
        blockers.append(f"{analysis_failures} analysis failure(s)")
    if clone_failures:
        blockers.append(f"{clone_failures} clone failure(s)")
    if not sourcecraft_live and not blockers:
        blockers.append("controlled SourceCraft AppSec live coverage is absent")
    return "Do not start Recommendation Engine: " + "; ".join(blockers) + "."


def compare_with_baseline(rows: list[dict[str, object]], baseline_path: Path | None) -> dict[str, object]:
    """Compare comparable category projections without treating scores as truth."""

    if baseline_path is None or not baseline_path.is_file():
        return {"status": "unavailable", "reason": "baseline summary was not supplied or does not exist"}
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "reason": f"baseline summary could not be read: {type(exc).__name__}"}
    if not isinstance(baseline, Mapping):
        return {"status": "unavailable", "reason": "baseline summary is not an object"}
    baseline_rows = {
        item.get("repository", {}).get("slug"): item
        for item in baseline.get("repositories", [])
        if isinstance(item, Mapping) and isinstance(item.get("repository"), Mapping)
    }
    comparisons = []
    for row in rows:
        repository = row.get("repository", {})
        if not isinstance(repository, Mapping):
            continue
        slug = repository.get("slug")
        before = baseline_rows.get(slug)
        current = next(
            (item for item in comparison_rows([row]) if isinstance(item, Mapping)),
            None,
        )
        before_comparison = next(
            (item for item in baseline.get("comparison", []) if isinstance(item, Mapping) and item.get("slug") == slug),
            None,
        )
        if not isinstance(before_comparison, Mapping) or not isinstance(current, Mapping):
            comparisons.append({"slug": slug, "status": "not_comparable"})
            continue
        category_deltas = {}
        for category in ("documentation", "activity", "code_health", "overall"):
            before_value = _number_or_none(before_comparison.get(category))
            current_value = _number_or_none(current.get(category))
            category_deltas[category] = {
                "before": before_value,
                "after": current_value,
                "delta": current_value - before_value
                if before_value is not None and current_value is not None
                else None,
            }
        current_head = row.get("clone", {}).get("head_sha") if isinstance(row.get("clone"), Mapping) else None
        before_head = (
            before.get("clone", {}).get("head_sha")
            if isinstance(before, Mapping) and isinstance(before.get("clone"), Mapping)
            else None
        )
        comparisons.append(
            {
                "slug": slug,
                "url": repository.get("url"),
                "baseline_head_sha": before_head,
                "current_head_sha": current_head,
                "same_head": bool(before_head and current_head and before_head == current_head),
                "category_scores": category_deltas,
                "before_outcome": before_comparison.get("outcome"),
                "after_outcome": current.get("outcome"),
            }
        )
    return {
        "status": "available",
        "path": str(baseline_path).replace("\\", "/"),
        "baseline_engine_validation_status": baseline.get("engine_validation_status"),
        "rows": comparisons,
    }


def comparison_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for row in rows:
        categories = row.get("analysis", {}).get("categories", []) if isinstance(row.get("analysis"), Mapping) else []
        scores = {item.get("category"): item.get("score") for item in categories if isinstance(item, Mapping)}
        status = row.get("analysis", {}).get("score", {}) if isinstance(row.get("analysis"), Mapping) else {}
        output.append(
            {
                "repository": row["repository"]["name"],
                "slug": row["repository"]["slug"],
                "url": row["repository"]["url"],
                "type": row["repository"]["repository_type"],
                "documentation": scores.get("documentation"),
                "activity": scores.get("activity"),
                "code_health": scores.get("code_health"),
                "overall": status.get("overall_score") if isinstance(status, Mapping) else None,
                "local_coverage": _local_coverage(row),
                "presentation_state": status.get("presentation_state") if isinstance(status, Mapping) else "N/A",
                "outcome": row["outcome"],
                "major_observations": _major_observations(row),
            }
        )
    return output


def evaluate_hypotheses(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        _h1_mvp_not_healthier(rows),
        _h2_todo_separation(rows),
        _h3_adversarial_substance(rows),
        _h4_large_no_size_penalty(rows),
        _h5_tiny_not_automatically_healthy(rows),
        _h6_unavailable_not_zero(rows),
        _h7_coverage_confidence(rows),
        _h8_source_scope(rows),
        _h9_documentation_variance(rows),
    ]


def detect_outliers(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    outliers: list[dict[str, object]] = []
    for row in rows:
        slug = row["repository"]["slug"]
        inventory = row.get("inventory", {})
        source_files = _number(inventory.get("source_file_count"))
        analysis = row.get("analysis")
        if not isinstance(analysis, Mapping):
            continue
        for category in analysis.get("categories", []):
            if not isinstance(category, Mapping):
                continue
            name = str(category.get("category"))
            score = _number_or_none(category.get("score"))
            evidence = _number(category.get("evidence_count"))
            coverage = category.get("coverage", {})
            confidence = category.get("confidence", {})
            if score is not None and _mapping(coverage, "status") == "unavailable":
                outliers.append(
                    _outlier(
                        slug, name, score, "unavailable coverage must not produce a numeric score", category, "BUG"
                    )
                )
            if score is not None and score >= 90 and evidence == 0:
                outliers.append(
                    _outlier(
                        slug,
                        name,
                        score,
                        "very high score should have non-empty evidence",
                        category,
                        "CALIBRATION QUESTION",
                    )
                )
            if score is not None and category.get("status") == "inconclusive":
                outliers.append(
                    _outlier(
                        slug,
                        name,
                        {"score": score, "status": category.get("status")},
                        "inconclusive categories must not expose a numeric score",
                        category,
                        "BUG",
                    )
                )
            if name == "code_health":
                missing_core = any(
                    isinstance(item, Mapping) and str(item.get("code", "")).startswith("sonarqube.")
                    for item in category.get("facts_limitations", [])
                )
                if missing_core and (
                    _mapping(coverage, "status") == "complete" or _mapping(confidence, "level") == "high"
                ):
                    outliers.append(
                        _outlier(
                            slug,
                            name,
                            {"coverage": coverage, "confidence": confidence},
                            "missing SonarQube core evidence must not look complete/high-confidence",
                            category,
                            "BUG",
                        )
                    )
            if name == "activity" and score is not None and score >= 90:
                commits = _observation(category, "unique_commits")
                if commits is not None and commits <= 2:
                    outliers.append(
                        _outlier(
                            slug,
                            name,
                            {"score": score, "unique_commits": commits},
                            "a tiny history should not look like a mature active project",
                            category,
                            "CALIBRATION QUESTION",
                        )
                    )
            if name == "code_health" and score is not None and score >= 90 and source_files <= 2:
                outliers.append(
                    _outlier(
                        slug,
                        name,
                        {"score": score, "source_file_count": source_files},
                        "a tiny source inventory should not silently become Code Health 100",
                        category,
                        "CALIBRATION QUESTION",
                    )
                )
            if (
                name in _SOURCECRAFT_CATEGORIES
                and category.get("live_verified") is False
                and (score is not None or category.get("status") not in {"skipped", "inconclusive", "error"})
            ):
                outliers.append(
                    _outlier(
                        slug,
                        name,
                        {"score": score, "status": category.get("status")},
                        "GitHub-only SourceCraft category must remain explicitly unavailable",
                        category,
                        "BUG",
                    )
                )
    return outliers


def classify_operational_observations(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Record known environment/data-shape limitations without calling them bugs."""

    observations: list[dict[str, object]] = []
    capabilities = next((row.get("capabilities", {}) for row in rows if row.get("capabilities")), {})
    for engine in ("vale", "git-sizer", "sonarqube"):
        state = _mapping(capabilities.get(engine), "state") if isinstance(capabilities, Mapping) else None
        if state != "available":
            observations.append(
                {
                    "repository": "matrix",
                    "category": engine,
                    "observed": state or "not reported",
                    "expected_relationship": "Optional external engine absence must remain explicit and degrade safely",
                    "possible_cause": _mapping(capabilities.get(engine), "reason")
                    if isinstance(capabilities, Mapping)
                    else "capability snapshot unavailable",
                    "classification": "LIMITATION",
                }
            )
    sourcecraft_state = (
        _mapping(capabilities.get("sourcecraft"), "state") if isinstance(capabilities, Mapping) else None
    )
    if sourcecraft_state != "available":
        observations.append(
            {
                "repository": "matrix",
                "category": "security",
                "observed": sourcecraft_state or "not reported",
                "expected_relationship": "GitHub-only validation cannot verify SourceCraft AppSec",
                "possible_cause": "controlled SourceCraft fixture is required",
                "classification": "LIMITATION",
            }
        )
    for row in rows:
        category = _category(row, "code_health")
        if category and category.get("facts_available") and category.get("score") is None:
            observations.append(
                {
                    "repository": row["repository"]["slug"],
                    "category": "code_health",
                    "observed": {
                        "status": category.get("status"),
                        "normalized_observations": category.get("normalized_observations"),
                    },
                    "expected_relationship": "TODO-only Code Health facts remain inconclusive when calibrated SonarQube/git-sizer components are absent",
                    "possible_cause": "This behavior is protected by the golden TODO-only Code Health test; no score is fabricated",
                    "classification": "EXPECTED BEHAVIOR",
                }
            )
    return observations


def _h1_mvp_not_healthier(rows: list[dict[str, object]]) -> dict[str, object]:
    mvp = _row(rows, "mvp-food")
    controls = [_row(rows, slug) for slug in ("andromeda", "ruff", "fastapi")]
    observations = []
    violations = 0
    comparisons = 0
    for category in ("documentation", "activity", "code_health"):
        mvp_score = _score(mvp, category)
        control_scores = [score for row in controls if (score := _score(row, category)) is not None]
        if mvp_score is None or not control_scores:
            continue
        comparisons += 1
        above = mvp_score > max(control_scores)
        violations += above
        observations.append({"category": category, "mvp": mvp_score, "controls": control_scores, "above_all": above})
    status = "NOT_TESTABLE" if not comparisons else "ANOMALY" if violations >= 2 else "PASS"
    return _hypothesis(
        "H1",
        status,
        observations,
        "MVP_FOOD should not outrank mature controls across categories",
        "available local category scores",
    )


def _h2_todo_separation(rows: list[dict[str, object]]) -> dict[str, object]:
    row = _row(rows, "todo")
    documentation = _score(row, "documentation")
    activity = _score(row, "activity")
    if documentation is None or activity is None:
        return _hypothesis(
            "H2",
            "NOT_TESTABLE",
            {"documentation": documentation, "activity": activity},
            "Documentation should be noticeably higher than Activity",
            "Vale or Git-derived category unavailable",
        )
    gap = documentation - activity
    status = "PASS" if gap >= 10 else "ANOMALY"
    return _hypothesis(
        "H2",
        status,
        {"documentation": documentation, "activity": activity, "gap": gap},
        "Documentation should be noticeably higher than Activity",
        "TODO category scores",
    )


def _h3_adversarial_substance(rows: list[dict[str, object]]) -> dict[str, object]:
    row = _row(rows, "two-cucumbersfloating")
    documentation = _score(row, "documentation")
    inventory = row.get("inventory", {}) if row else {}
    source_files = _number(inventory.get("source_file_count"))
    commits = _observation_from_row(row, "activity", "unique_commits")
    if documentation is None:
        status = "NOT_TESTABLE"
    else:
        # This corpus case is intentionally documentation-heavy but product-light.
        # Keep the gate qualitative: a handful of historical commits does not
        # constitute substantive product surface when the checkout has no source
        # files.  This threshold belongs to the validation hypothesis, not scoring.
        status = (
            "PASS" if documentation >= 70 and source_files <= 5 and (commits is None or commits <= 10) else "ANOMALY"
        )
    return _hypothesis(
        "H3",
        status,
        {"documentation": documentation, "source_file_count": source_files, "unique_commits": commits},
        "Good documentation may coexist with limited substantive product",
        "validation-only inventory plus available category results",
    )


def _h4_large_no_size_penalty(rows: list[dict[str, object]]) -> dict[str, object]:
    large = [_row(rows, slug) for slug in ("ruff", "uv", "fastapi", "pydantic")]
    small = [_row(rows, slug) for slug in ("mvp-food", "freshly", "todo")]
    large_scores = [score for row in large if (score := _score(row, "code_health")) is not None]
    small_scores = [score for row in small if (score := _score(row, "code_health")) is not None]
    if len(large_scores) < 2 or not small_scores:
        all_rows = [*large, *small]
        partial = [
            row
            for row in all_rows
            if (_category(row, "code_health") or {}).get("score") is None
            and _mapping((_category(row, "code_health") or {}).get("coverage"), "status") in {"partial", "unavailable"}
        ]
        status = "PASS" if len(partial) == len(all_rows) and all_rows else "NOT_TESTABLE"
        return _hypothesis(
            "H4",
            status,
            {"large_code_health": large_scores, "small_code_health": small_scores, "partial_rows": len(partial)},
            "Large mature repositories should not be systematically penalized only for size",
            "Code Health numeric availability and explicit partial coverage",
        )
    status = "PASS" if statistics.median(large_scores) >= statistics.median(small_scores) * 0.75 else "ANOMALY"
    return _hypothesis(
        "H4",
        status,
        {"large_code_health": large_scores, "small_code_health": small_scores},
        "Large mature repositories should not be systematically penalized only for size",
        "relative Code Health medians",
    )


def _h5_tiny_not_automatically_healthy(rows: list[dict[str, object]]) -> dict[str, object]:
    observations = []
    anomaly = False
    for row in rows:
        source_files = _number(row.get("inventory", {}).get("source_file_count"))
        if source_files > 2:
            continue
        category = _category(row, "code_health") or {}
        score = _number_or_none(category.get("score"))
        components = category.get("component_scores", {})
        core_present = isinstance(components, Mapping) and any(
            key in components for key in ("maintainability_debt", "complexity", "duplication", "hotspots_churn")
        )
        observations.append(
            {
                "slug": row["repository"]["slug"],
                "source_file_count": source_files,
                "code_health": score,
                "status": category.get("status"),
                "coverage": category.get("coverage"),
                "core_components_present": core_present,
            }
        )
        anomaly = anomaly or (score is not None and not core_present)
    return _hypothesis(
        "H5",
        "ANOMALY" if anomaly else "PASS" if observations else "NOT_TESTABLE",
        observations,
        "Tiny repositories should not receive an unjustifiably high Code Health from absent complexity/duplication",
        "source inventory, core component evidence, and Code Health",
    )


def _h6_unavailable_not_zero(rows: list[dict[str, object]]) -> dict[str, object]:
    checks = []
    for row in rows:
        for category in _SOURCECRAFT_CATEGORIES:
            result = _category(row, category)
            if result is not None:
                checks.append(
                    {
                        "slug": row["repository"]["slug"],
                        "category": category,
                        "score": result.get("score"),
                        "status": result.get("status"),
                        "coverage": _mapping(result.get("coverage"), "status"),
                    }
                )
    valid = bool(checks) and all(
        item["score"] is None and item["coverage"] in {"unavailable", "partial"} for item in checks
    )
    return _hypothesis(
        "H6",
        "PASS" if valid else "ANOMALY",
        checks,
        "Unavailable GitHub-only SourceCraft metrics must not become numeric zero",
        "SourceCraft-only category projections",
    )


def _h7_coverage_confidence(rows: list[dict[str, object]]) -> dict[str, object]:
    checks = []
    for row in rows:
        for category in _SOURCECRAFT_CATEGORIES:
            result = _category(row, category)
            if result is not None:
                checks.append(
                    {
                        "slug": row["repository"]["slug"],
                        "category": category,
                        "coverage": result.get("coverage"),
                        "confidence": result.get("confidence"),
                    }
                )
    valid = bool(checks) and all(
        _mapping(item["coverage"], "status") in {"unavailable", "partial"}
        and _mapping(item["confidence"], "level") in {"unknown", "low"}
        for item in checks
    )
    return _hypothesis(
        "H7",
        "PASS" if valid else "ANOMALY",
        checks,
        "Coverage/confidence must show SourceCraft was not checked on GitHub",
        "SourceCraft-only category coverage/confidence",
    )


def _h8_source_scope(rows: list[dict[str, object]]) -> dict[str, object]:
    checks = []
    for row in rows:
        for category in ("issues", "cicd"):
            result = _category(row, category)
            if result is not None:
                checks.append(
                    {
                        "slug": row["repository"]["slug"],
                        "category": category,
                        "source": result.get("source"),
                        "status": result.get("status"),
                        "score": result.get("score"),
                    }
                )
    valid = bool(checks) and all(
        item["score"] is None
        and item["status"] in {"skipped", "inconclusive"}
        and item["source"] in {"SourceCraft Issues REST", "SourceCraft CI/CD REST"}
        for item in checks
    )
    return _hypothesis(
        "H8",
        "PASS" if valid else "ANOMALY",
        checks,
        "Issues and CI/CD must not be mislabeled as SourceCraft-backed or populated from GitHub APIs",
        "production source mapping and unavailable category projections",
    )


def _h9_documentation_variance(rows: list[dict[str, object]]) -> dict[str, object]:
    scores = [score for row in rows if (score := _score(row, "documentation")) is not None]
    if len(scores) < 6:
        return _hypothesis(
            "H9",
            "NOT_TESTABLE",
            {"scores": scores},
            "Documentation should not collapse to one value across the corpus",
            "available Documentation category scores",
        )
    rounded = [round(score, 2) for score in scores]
    most_common = max(rounded.count(value) for value in set(rounded))
    collapsed = most_common / len(rounded) >= 0.8
    return _hypothesis(
        "H9",
        "ANOMALY" if collapsed else "PASS",
        {"scores": scores, "most_common_fraction": most_common / len(rounded)},
        "Documentation should not collapse to one value across the corpus",
        "relative score variance",
    )


def _manual_deep_dive(row: dict[str, object], output_root: Path) -> dict[str, object]:
    analysis = row.get("analysis") if isinstance(row.get("analysis"), Mapping) else {}
    categories = analysis.get("categories", []) if isinstance(analysis, Mapping) else []
    return {
        "slug": row["repository"]["slug"],
        "url": row["repository"]["url"],
        "json_artifact": f"{output_root.as_posix()}/repositories/{row['repository']['slug']}.json",
        "head_sha": row.get("clone", {}).get("head_sha") if isinstance(row.get("clone"), Mapping) else None,
        "raw_normalized_facts": analysis.get("facts", {}) if isinstance(analysis, Mapping) else {},
        "categories": [
            {
                "category": item.get("category"),
                "status": item.get("status"),
                "score": item.get("score"),
                "coverage": item.get("coverage"),
                "confidence": item.get("confidence"),
                "component_scores": item.get("component_scores"),
                "formula_substitution": item.get("formula_substitution"),
                "evidence_count": item.get("evidence_count"),
                "limitations": item.get("limitations"),
            }
            for item in categories
            if isinstance(item, Mapping)
        ],
    }


def render_summary_markdown(summary: Mapping[str, object]) -> str:
    rows = summary.get("comparison", [])
    lines = [
        "# Current Repo Health Engine Validation",
        "",
        "This report records observed behavior of the existing production engine. It is not a calibration change and does not treat any absolute score as ground truth.",
        "",
        f"Engine validation status: **{summary.get('engine_validation_status', 'N/A')}**",
        f"Safe to proceed to Recommendation Engine: **{'YES' if summary.get('safe_to_proceed_to_recommendation_engine') else 'NO'}**",
        f"Reason: {summary.get('safe_to_proceed_reason', 'N/A')}",
        "",
        "## Methodology",
        "",
        "Each public GitHub URL was cloned into an isolated ignored checkout and run through the canonical production composition root (with the narrow Vale JSON compatibility fix recorded below): Git/PyDriller/Vale/SonarQube/git-sizer/TODO collectors as available → normalized RepositoryFacts → six analyzers → ScoreEngineV1. GitHub Issues, GitHub Actions, CodeQL, Dependabot, and other GitHub APIs were never used as SourceCraft substitutes.",
        "",
        f"Run as-of: `{summary.get('as_of', 'N/A')}`; repositories attempted: `{summary.get('repository_count', 0)}`; artifacts: `{summary.get('artifact_root', 'N/A')}`",
        "",
        "## Tool and environment evidence",
        "",
        _environment_markdown(summary.get("environment")),
        "",
        "## Comparison table",
        "",
        _comparison_markdown(rows),
        "",
        "## Before/after baseline comparison",
        "",
        _baseline_markdown(summary.get("baseline_comparison")),
        "",
        "## Hypotheses",
        "",
        _hypotheses_markdown(summary.get("hypotheses")),
        "",
        "## Anomalies and classifications",
        "",
        _outliers_markdown(summary.get("outliers")),
        "",
        "## Actual bugs",
        "",
        _bullet_or_none(summary.get("actual_bugs")),
        "",
        "## Calibration questions",
        "",
        _bullet_or_none(summary.get("calibration_questions")),
        "",
        "## Expected behavior",
        "",
        _bullet_or_none(summary.get("expected_behavior")),
        "",
        "## Limitations",
        "",
        _bullet_or_none(summary.get("limitations")),
        "",
        "## Manual deep-dives",
        "",
        _deep_dives_markdown(summary.get("manual_deep_dives")),
        "",
        "## Performance",
        "",
        _performance_markdown(summary.get("performance")),
        "",
        "## SourceCraft-specific validation scope",
        "",
        "Security is SourceCraft AppSec-only in this product. Issues and CI/CD have no configured production provider and are not substituted with GitHub APIs. This GitHub validation proves unavailable/partial state, coverage, confidence, and evidence semantics; a controlled SourceCraft fixture with safe synthetic findings is still required for live AppSec provider validation.",
        "",
        "## Interpretation",
        "",
        "Observed anomalies are evidence for follow-up investigation. This run intentionally does not modify weights, calibration-v2, Score Engine v1, security caps, coverage/confidence formulas, or analyzer formulas.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_current_engine_report(summary: Mapping[str, object], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_summary_markdown(summary), encoding="utf-8")


def _comparison_markdown(rows: object) -> str:
    table = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping):
            table.append(
                [
                    f"[{row.get('repository')}]({row.get('url', '')})" if row.get("url") else row.get("repository"),
                    row.get("type"),
                    _fmt(row.get("documentation")),
                    _fmt(row.get("activity")),
                    _fmt(row.get("code_health")),
                    row.get("local_coverage"),
                    row.get("presentation_state"),
                    row.get("major_observations"),
                ]
            )
    return _table(
        (
            "Repository",
            "Type",
            "Documentation",
            "Activity",
            "Code Health",
            "Local Coverage",
            "Overall state",
            "Major observations",
        ),
        table,
    )


def _environment_markdown(value: object) -> str:
    if not isinstance(value, Mapping):
        return "Environment evidence unavailable."
    capabilities = value.get("capabilities", {})
    rows = []
    if isinstance(capabilities, Mapping):
        for name, capability in sorted(capabilities.items()):
            if isinstance(capability, Mapping):
                rows.append([name, capability.get("state"), capability.get("reason")])
    text = _table(("Engine", "State", "Reason"), rows)
    pinned = value.get("pinned_tools")
    if isinstance(pinned, Mapping):
        text += "\n\nPinned tool manifest (URLs/SHA-256 only; no credentials):\n\n```json\n"
        text += json.dumps(pinned, ensure_ascii=False, indent=2, sort_keys=True)
        text += "\n```"
    notes = value.get("adapter_notes")
    if isinstance(notes, list) and notes:
        text += "\n\nValidation implementation notes:\n\n" + "\n".join(f"- {item}" for item in notes)
    return text


def _hypotheses_markdown(items: object) -> str:
    rows = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, Mapping):
            rows.append(
                [
                    item.get("id"),
                    item.get("status"),
                    item.get("expected_relationship"),
                    item.get("classification"),
                    item.get("possible_cause"),
                ]
            )
    return _table(("ID", "Status", "Expected relationship", "Classification", "Evidence/cause"), rows)


def _outliers_markdown(items: object) -> str:
    rows = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, Mapping):
            rows.append(
                [
                    item.get("repository"),
                    item.get("category"),
                    item.get("classification"),
                    item.get("observed"),
                    item.get("expected_relationship"),
                    item.get("possible_cause"),
                ]
            )
    return _table(("Repository", "Category", "Class", "Observed", "Expected", "Possible cause"), rows)


def _deep_dives_markdown(items: object) -> str:
    lines = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        lines.extend(
            [
                f"### {item.get('slug')}",
                "",
                f"Repository: [{item.get('url')}]({item.get('url')})",
                f"Resolved HEAD: `{item.get('head_sha') or 'N/A'}`",
                f"Machine-readable artifact: `{item.get('json_artifact')}`",
                "",
            ]
        )
        categories = item.get("categories", [])
        rows = []
        for category in categories if isinstance(categories, list) else []:
            if isinstance(category, Mapping):
                rows.append(
                    [
                        category.get("category"),
                        category.get("status"),
                        _fmt(category.get("score")),
                        _fmt_ratio(_mapping(category.get("coverage"), "status")),
                        _mapping(category.get("confidence"), "level"),
                        category.get("evidence_count"),
                        category.get("formula_substitution"),
                    ]
                )
        lines.extend(
            [
                _table(
                    ("Category", "Status", "Score", "Coverage", "Confidence", "Evidence", "Formula substitution"), rows
                ),
                "",
            ]
        )
        lines.extend(
            [
                "Raw normalized facts:",
                "",
                "```json",
                json.dumps(item.get("raw_normalized_facts", {}), ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    return "\n".join(lines) if lines else "No manual deep-dives were available."


def _performance_markdown(items: object) -> str:
    rows = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, Mapping):
            rows.append(
                [
                    item.get("slug"),
                    item.get("type"),
                    item.get("clone_ms"),
                    item.get("collection_ms"),
                    item.get("normalization_ms"),
                    item.get("analyzer_ms"),
                    item.get("score_engine_ms"),
                    item.get("total_ms"),
                ]
            )
    return _table(
        (
            "Repository",
            "Type",
            "Clone ms",
            "Collection ms",
            "Normalization ms",
            "Analyzer ms",
            "Score engine ms",
            "Total ms",
        ),
        rows,
    )


def _baseline_markdown(value: object) -> str:
    if not isinstance(value, Mapping):
        return "Baseline comparison unavailable."
    if value.get("status") != "available":
        return f"Baseline comparison unavailable: `{value.get('reason', 'unknown reason')}`"
    rows = []
    for item in value.get("rows", []) if isinstance(value.get("rows"), list) else []:
        if not isinstance(item, Mapping):
            continue
        scores = item.get("category_scores", {})
        rows.append(
            [
                item.get("slug"),
                "YES" if item.get("same_head") else "NO",
                _delta_cell(scores, "documentation"),
                _delta_cell(scores, "activity"),
                _delta_cell(scores, "code_health"),
                item.get("before_outcome"),
                item.get("after_outcome"),
            ]
        )
    baseline_status = value.get("baseline_engine_validation_status")
    if baseline_status == "PASS WITH ANOMALIES":
        baseline_status = "PASS WITH COVERAGE LIMITATIONS (normalized from historical baseline label)"
    return f"Baseline: `{value.get('path')}`; baseline status: `{baseline_status}`\n\n" + _table(
        (
            "Repository",
            "Same HEAD",
            "Documentation before→after",
            "Activity before→after",
            "Code Health before→after",
            "Before outcome",
            "After outcome",
        ),
        rows,
    )


def _delta_cell(scores: object, category: str) -> str:
    value = scores.get(category) if isinstance(scores, Mapping) else None
    if not isinstance(value, Mapping):
        return "N/A"
    before = _fmt(value.get("before"))
    after = _fmt(value.get("after"))
    delta = _fmt(value.get("delta"))
    return f"{before} → {after} (Δ {delta})"


def _bullet_or_none(items: object) -> str:
    if not isinstance(items, list) or not items:
        return "None recorded."
    return "\n".join(
        f"- `{item.get('repository', item.get('id', 'item'))}`: {item.get('possible_cause', item.get('expected_relationship', item))}"
        for item in items
        if isinstance(item, Mapping)
    )


def _table(headers: tuple[str, ...], rows: list[list[object]]) -> str:
    if not rows:
        rows = [["N/A" for _ in headers]]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows],
        ]
    )


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _hypothesis(identifier: str, status: str, observed: object, expected: str, evidence: str) -> dict[str, object]:
    classification = (
        "EXPECTED BEHAVIOR"
        if identifier in {"H6", "H7"} and status == "PASS"
        else "CALIBRATION QUESTION"
        if status == "ANOMALY"
        else "LIMITATION"
        if status == "NOT_TESTABLE"
        else "EXPECTED BEHAVIOR"
    )
    return {
        "id": identifier,
        "status": status,
        "observed": observed,
        "expected_relationship": expected,
        "evidence": evidence,
        "possible_cause": evidence,
        "classification": classification,
    }


def _outlier(
    repository: str, category: str, observed: object, expected: str, evidence: Mapping[str, object], classification: str
) -> dict[str, object]:
    return {
        "repository": repository,
        "category": category,
        "observed": observed,
        "expected_relationship": expected,
        "evidence": {
            "status": evidence.get("status"),
            "score": evidence.get("score"),
            "coverage": evidence.get("coverage"),
            "confidence": evidence.get("confidence"),
            "evidence_count": evidence.get("evidence_count"),
            "limitations": evidence.get("limitations"),
        },
        "possible_cause": "validation-only suspicious result; inspect normalized facts and current policy before any decision",
        "classification": classification,
    }


def _row(rows: list[dict[str, object]], slug: str) -> dict[str, object]:
    return next((row for row in rows if row.get("repository", {}).get("slug") == slug), {})


def _category(row: Mapping[str, object], category: str) -> dict[str, object] | None:
    analysis = row.get("analysis")
    if not isinstance(analysis, Mapping):
        return None
    return next(
        (
            item
            for item in analysis.get("categories", [])
            if isinstance(item, Mapping) and item.get("category") == category
        ),
        None,
    )


def _score(row: Mapping[str, object], category: str) -> float | None:
    item = _category(row, category)
    return _number_or_none(item.get("score")) if item else None


def _observation(category: Mapping[str, object], key: str) -> float | None:
    for item in (
        category.get("normalized_observations", []) if isinstance(category.get("normalized_observations"), list) else []
    ):
        if isinstance(item, Mapping) and item.get("key") == key:
            return _number_or_none(item.get("value"))
    return None


def _observation_from_row(row: Mapping[str, object], category: str, key: str) -> float | None:
    item = _category(row, category)
    return _observation(item, key) if item else None


def _local_coverage(row: Mapping[str, object]) -> str:
    analysis = row.get("analysis")
    if not isinstance(analysis, Mapping):
        return "none"
    categories = analysis.get("categories", [])
    available = [item for item in categories if isinstance(item, Mapping) and item.get("live_verified")]
    return f"{len(available)}/{len(categories)} production capabilities live" if categories else "none"


def _major_observations(row: Mapping[str, object]) -> str:
    notes = []
    inventory = row.get("inventory", {})
    if isinstance(inventory, Mapping) and inventory.get("artifact_count"):
        notes.append(f"artifacts={inventory['artifact_count']}")
    if isinstance(row.get("analysis"), Mapping):
        for category in row["analysis"].get("categories", []):
            if isinstance(category, Mapping) and category.get("limitations"):
                notes.append(f"{category.get('category')}:partial/unavailable")
    return "; ".join(notes) or "no special observation"


def _mapping(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, Mapping) else None


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _number_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--checkout-root", type=Path, default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--repo", action="append", dest="slugs", default=None)
    parser.add_argument("--clone-timeout", type=float, default=600.0)
    parser.add_argument("--analysis-timeout", type=float, default=900.0)
    parser.add_argument("--enable-sonarqube", action="store_true")
    parser.add_argument("--sonar-url", default=None)
    parser.add_argument("--baseline-summary", type=Path, default=DEFAULT_BASELINE_SUMMARY)
    parser.add_argument("--report-path", type=Path, default=Path("docs/validation/current-engine-validation.md"))
    args = parser.parse_args(argv)
    try:
        as_of = _parse_as_of(args.as_of)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        manifest_digest = hashlib.sha256(
            json.dumps([item.url for item in REPOSITORY_MANIFEST], separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:8]
        run_id = f"{run_id}-{manifest_digest}"
        output_root = args.output_root or Path("artifacts/validation") / run_id
        checkout_root = args.checkout_root or default_checkout_root(run_id)
        summary = run_matrix(
            output_root=output_root,
            checkout_root=checkout_root,
            as_of=as_of,
            selected_slugs=set(args.slugs) if args.slugs else None,
            clone_timeout_seconds=args.clone_timeout,
            analysis_timeout_seconds=args.analysis_timeout,
            enable_sonarqube=args.enable_sonarqube,
            sonar_url=args.sonar_url,
            sonar_token=os.getenv("SONAR_TOKEN"),
            baseline_summary_path=args.baseline_summary,
        )
        if args.report_path:
            write_current_engine_report(summary, args.report_path)
        print(
            json.dumps(
                {
                    "summary": str(output_root / "summary.json"),
                    "report": str(args.report_path) if args.report_path else None,
                    "engine_validation_status": summary["engine_validation_status"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:512]}, ensure_ascii=False
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_summary", "detect_outliers", "evaluate_hypotheses", "main", "render_summary_markdown", "run_matrix"]
