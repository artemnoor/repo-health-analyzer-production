#!/usr/bin/env python3
"""Non-production v2 calibration for Repo Health category scores.

This runner is deliberately experimental.  It reuses the repository's
existing adapter boundaries, starts from real SourceCraft checkouts and
inventories, and writes only redacted observations under ``calibration-v2``.
It never changes the production Score Engine or category analyzers.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx

from repowise.core.analysis.health.calibration_policy_v2 import (
    activity_score,
    cicd_component_score,
    documentation_score,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "spikes" / "scoring" / "calibration-v2"
EXTERNAL_ROOT = Path(os.environ.get("REPO_HEALTH_CALIBRATION_ROOT", "D:/RepoHealthCalibration"))
CONTROLLED_ROOT = EXTERNAL_ROOT / os.environ.get("REPO_HEALTH_CALIBRATION_V2_CONTROLLED_DIR", "controlled-v2")
SONAR_URL = os.environ.get("REPO_HEALTH_SONAR_URL", "http://127.0.0.1:9000")
SONAR_SCANNER = Path(os.environ.get("REPO_HEALTH_SONAR_SCANNER", str(EXTERNAL_ROOT / "tools" / "sonar-scanner" / "sonar-scanner-8.1.0.6389-windows-x64" / "bin" / "sonar-scanner.bat")))
AS_OF = datetime(2026, 9, 20, 23, 59, 59, tzinfo=UTC)
OBSERVATIONAL_LIMIT = int(os.environ.get("REPO_HEALTH_CALIBRATION_V2_N", "32"))
WEIGHTS = {"Documentation": 15.0, "Activity": 15.0, "Issues": 15.0, "CI/CD": 15.0, "Security": 20.0, "Code Health": 20.0}
MISSING_STATUSES = {"UNAVAILABLE", "ERROR", "NOT_APPLICABLE", "NO_ACTIVITY", "CI_NOT_CONFIGURED", "NO_RUNS"}


def load_v1() -> Any:
    path = ROOT / "spikes" / "scoring" / "calibration" / "run_calibration.py"
    spec = importlib.util.spec_from_file_location("repo_health_calibration_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load calibration helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install_verification_shim()
    return module


def num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def bounded(value: object, default: float = 0.0) -> float:
    result = num(value)
    return max(0.0, min(1.0, result if result is not None else default))


def metric(category: dict[str, Any], *names: str) -> float | None:
    values = category.get("metrics") if isinstance(category.get("metrics"), dict) else {}
    for name in names:
        value = num(values.get(name))
        if value is not None:
            return value
    return None


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def pct(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "min": None, "max": None}
    return {"n": len(values), "mean": statistics.fmean(values), "median": statistics.median(values), "p10": pct(values, .10), "p25": pct(values, .25), "p50": pct(values, .50), "p75": pct(values, .75), "p90": pct(values, .90), "min": min(values), "max": max(values)}


def ranks(values: list[float]) -> list[float]:
    pairs = sorted((value, index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average = (index + 1 + end) / 2.0
        for _, original in pairs[index:end]:
            result[original] = average
        index = end
    return result


def spearman(left: list[float | None], right: list[float | None]) -> tuple[float | None, int]:
    rows = [(a, b) for a, b in zip(left, right, strict=True) if a is not None and b is not None]
    if len(rows) < 3:
        return None, len(rows)
    lr, rr = ranks([float(a) for a, _ in rows]), ranks([float(b) for _, b in rows])
    ml, mr = statistics.fmean(lr), statistics.fmean(rr)
    denominator = math.sqrt(sum((x - ml) ** 2 for x in lr) * sum((y - mr) ** 2 for y in rr))
    return (sum((x - ml) * (y - mr) for x, y in zip(lr, rr, strict=True)) / denominator if denominator else 0.0), len(rows)


def run_cmd(args: list[str], cwd: Path, *, timeout: int = 300, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False, env=env)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def project(category_result: Any, source_status: str | None = None) -> dict[str, Any]:
    """Redact an AnalyzerResult without preserving prose, source, logs or tokens."""
    diagnostics = category_result.diagnostics if isinstance(category_result.diagnostics, dict) else {}
    coverage = diagnostics.get("coverage")
    confidence = diagnostics.get("confidence")
    for key in ("pydriller", "issues", "cicd", "code_health"):
        nested = diagnostics.get(key)
        if isinstance(nested, dict):
            coverage = nested.get("coverage", coverage)
            confidence = nested.get("confidence", confidence)
    status = str(source_status or diagnostics.get("execution_status") or diagnostics.get("issues_status") or diagnostics.get("cicd_status") or category_result.status.value).upper()
    if status in {"PASS", "WARN", "FAIL", "INCONCLUSIVE", "SKIPPED"}:
        status = "MEASURED" if category_result.score is not None else "UNAVAILABLE"
    evidence: list[dict[str, Any]] = []
    for ref in category_result.evidence[:40]:
        evidence.append({"source": ref.source, "path": ref.path, "line": ref.line_start, "json_pointer": ref.json_pointer, "confidence": ref.confidence, "redaction": ref.redaction})
    return {
        "analyzer_id": category_result.analyzer_id,
        "status": category_result.status.value,
        "category_status": status,
        "score": category_result.score,
        "coverage": bounded(coverage, 1.0 if category_result.score is not None else 0.0),
        "confidence": bounded(confidence, 1.0 if category_result.score is not None else 0.0),
        "metrics": {str(item.name): item.value for item in category_result.metrics},
        "finding_count": len(category_result.findings),
        "limitation_count": len(category_result.limitations),
        "evidence": evidence,
        "diagnostics": {key: diagnostics[key] for key in ("pydriller_status", "pydriller_score", "issues_status", "cicd_status", "code_health", "code_health_components", "code_health_score_before", "code_health_score_after", "sonar_status") if key in diagnostics},
    }


def documentation_completeness(path: Path) -> tuple[float, float, dict[str, Any]]:
    files = {item.relative_to(path).as_posix().casefold() for item in path.rglob("*") if item.is_file() and ".git" not in item.parts and not any(part in {"vendor", "generated", "build", "dist", "node_modules"} for part in item.parts)}
    readme = any(item == "readme.md" or item.startswith("readme.") for item in files)
    license_file = any(item.startswith("license") for item in files)
    contributing = any(item.startswith("contributing") for item in files)
    codeowners = any(item == "codeowners" or item.endswith("/codeowners") for item in files)
    text = "\n".join((path / item).read_text(encoding="utf-8", errors="ignore") for item in files if item.endswith((".md", ".rst", ".txt")) and (path / item).exists())
    instructions = bool(re.search(r"\b(install|setup|run|build|test|usage|quickstart)\b", text, flags=re.IGNORECASE))
    completeness = 100.0 * sum((readme, license_file, contributing, codeowners)) / 4.0
    instruction_score = 100.0 if instructions else 0.0
    return completeness, instruction_score, {"readme": readme, "license": license_file, "contributing": contributing, "codeowners": codeowners, "instructions": instructions}


def recalibrate_documentation(category: dict[str, Any], path: Path) -> dict[str, Any]:
    completeness, instructions, presence = documentation_completeness(path)
    words = metric(category, "vale:words") or 0.0
    findings = metric(category, "vale_weighted_finding_points", "vale_findings") or 0.0
    complex_words = metric(category, "vale:complex_words") or 0.0
    long_words = metric(category, "vale:long_words") or 0.0
    if category.get("category_status") in MISSING_STATUSES:
        category["calibration_v2_score"] = None
        category["calibration_v2_components"] = {"status": category.get("category_status")}
        return category
    quality_penalty = min(100.0, findings * 10.0 + findings / max(words, 500.0) * 600.0)
    readability = max(0.0, 100.0 - 100.0 * (complex_words / max(words, 1.0)) - 60.0 * (long_words / max(words, 1.0)))
    quality = max(0.0, 100.0 - quality_penalty)
    score = documentation_score(
        completeness=completeness,
        instructions=instructions,
        vale_quality=quality,
        readability=readability,
    )
    category["calibration_v2_score"] = round(max(0.0, min(100.0, score)), 6)
    category["calibration_v2_components"] = {"completeness": completeness, "instructions": instructions, "vale_quality": quality, "readability": readability, "presence": presence, "words": words, "finding_points": findings}
    return category


def recalibrate_activity(category: dict[str, Any]) -> dict[str, Any]:
    if category.get("category_status") in MISSING_STATUSES:
        category["calibration_v2_score"] = None
        return category
    commits = metric(category, "pydriller:unique_commits", "pydriller:commit_occurrences") or 0.0
    age = metric(category, "pydriller:latest_activity_age_days")
    meaningful = bounded(metric(category, "pydriller:meaningful_activity_ratio"), 0.0)
    commits_90 = metric(category, "pydriller:commits_90d") or 0.0
    authors_90 = metric(category, "pydriller:authors_90d") or 0.0
    empty_commits = metric(category, "pydriller:empty_commits") or 0.0
    score, components = activity_score(
        unique_commits=commits,
        latest_age_days=age,
        meaningful_ratio=meaningful,
        commits_90d=commits_90,
        authors_90d=authors_90,
        empty_commits=empty_commits,
    )
    category["calibration_v2_score"] = round(score, 6)
    category["calibration_v2_components"] = {**components, "commits": commits}
    return category


def recalibrate_issues(category: dict[str, Any]) -> dict[str, Any]:
    sample = metric(category, "issues:sample_size")
    if category.get("category_status") in MISSING_STATUSES or sample is None or sample < 5.0:
        category["calibration_v2_score"] = None
        category["calibration_v2_components"] = {"sample": sample, "reason": "minimum_sample_5"}
    else:
        category["calibration_v2_score"] = category.get("score")
        category["calibration_v2_components"] = {"sample": sample, "source_score": category.get("score")}
    return category


def anchored_quality(value: float, anchors: tuple[tuple[float, float], ...]) -> float:
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (left_x, left_y), (right_x, right_y) in pairwise(anchors):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    return anchors[-1][1]


def recalibrate_cicd(category: dict[str, Any]) -> dict[str, Any]:
    runs = metric(category, "cicd:total_runs") or metric(category, "cicd:terminal_runs") or 0.0
    failures = metric(category, "cicd:failure_rate")
    if category.get("category_status") in MISSING_STATUSES or runs < 5 or failures is None:
        category["calibration_v2_score"] = None
        category["calibration_v2_components"] = {"runs": runs, "failure_rate": failures}
        return category
    streak = metric(category, "cicd:consecutive_failure_streak", "cicd:current:failure_streak") or 0.0
    p50 = metric(
        category,
        "cicd:p50_seconds",
        "cicd:duration_p50_seconds",
        "cicd:current:duration_p50_seconds",
    )
    p95 = metric(
        category,
        "cicd:p95_seconds",
        "cicd:duration_p95_seconds",
        "cicd:current:duration_p95_seconds",
    )
    delta = metric(category, "cicd:failure_rate_delta")
    score, components, _eligible = cicd_component_score(
        failure_rate=failures,
        failure_streak=int(streak),
        p50_seconds=p50,
        p95_seconds=p95,
        failure_rate_delta=delta,
    )
    category["calibration_v2_score"] = round(score, 6) if score is not None else None
    category["calibration_v2_components"] = {**components, "runs": runs, "failure_rate": failures}
    return category


def recalibrate_code_health(category: dict[str, Any]) -> dict[str, Any]:
    if category.get("category_status") in MISSING_STATUSES or category.get("score") is None:
        category["calibration_v2_score"] = None
    else:
        category["calibration_v2_score"] = category.get("score")
    return category


def effective_categories(categories: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for name, item in categories.items():
        row = dict(item)
        row["score"] = row.get("calibration_v2_score")
        result[name] = row
    return result


def top_level(categories: dict[str, dict[str, Any]], *, weights: dict[str, float] = WEIGHTS, security_cap: float | None = None) -> dict[str, Any]:
    measured = {name: item for name, item in categories.items() if item.get("category_status") not in MISSING_STATUSES and num(item.get("score")) is not None}
    rows = [(weights[name], num(item.get("score")), bounded(item.get("coverage")) * bounded(item.get("confidence"))) for name, item in measured.items() if name in weights]
    if not rows:
        return {"h_arithmetic": None, "h_geometric": None, "h_hybrid": None, "k": 0.0, "state": "INSUFFICIENT_DATA", "measured_categories": 0}
    h_arith = sum(weight * score for weight, score, _ in rows) / sum(weight for weight, _, _ in rows)
    epsilon = 1e-6
    h_geo = math.exp(sum(weight * math.log(max(epsilon, score)) for weight, score, _ in rows) / sum(weight for weight, _, _ in rows))
    k = sum(weights[name] * bounded(item.get("coverage")) * bounded(item.get("confidence")) for name, item in categories.items()) / sum(weights.values())
    h_hybrid = min(h_arith, security_cap) if security_cap is not None else h_arith
    if k >= 0.75 and len(measured) >= 5:
        state = "SCORE"
    elif k >= 0.50 and len(measured) >= 4:
        state = "PROVISIONAL_SCORE"
    else:
        state = "INSUFFICIENT_DATA"
    return {"h_arithmetic": round(h_arith, 6), "h_geometric": round(h_geo, 6), "h_hybrid": round(h_hybrid, 6), "k": round(k, 6), "state": state, "measured_categories": len(measured), "security_cap": security_cap}


def synthetic_security(score: float, severity: str, *, status: str = "MEASURED") -> dict[str, Any]:
    return {"analyzer_id": "sourcecraft.appsec.synthetic-calibration", "status": "pass" if score >= 80 else "fail", "category_status": status, "score": score if status == "MEASURED" else None, "coverage": 1.0 if status == "MEASURED" else 0.0, "confidence": 1.0 if status == "MEASURED" else 0.0, "metrics": {"appsec:severity": severity, "appsec:synthetic": True}, "finding_count": 0 if severity == "none" else 1, "limitation_count": 0, "evidence": [{"source": "controlled.synthetic_appsec", "path": None, "line": None, "json_pointer": "/findings/0", "confidence": 1.0, "redaction": "full"}], "diagnostics": {"synthetic": True, "severity": severity}}


def scan_sonar(path: Path, project_key: str, token: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not SONAR_SCANNER.exists() or not token:
        return None, {"status": "UNAVAILABLE", "reason": "scanner_or_token_missing"}
    # SonarScanner reads SONAR_TOKEN from the child environment.  Do not put
    # credentials in command-line arguments: process listings are observable.
    args = ["-Dsonar.projectKey=" + project_key, "-Dsonar.projectName=" + project_key, "-Dsonar.sources=.", "-Dsonar.host.url=" + SONAR_URL, "-Dsonar.scm.disabled=true", "-Dsonar.exclusions=**/.git/**,**/vendor/**,**/generated/**,**/build/**,**/dist/**,**/node_modules/**,**/coverage/**,**/*.min.js"]
    try:
        completed = run_cmd([str(SONAR_SCANNER), *args], path, timeout=900, env={**os.environ, "SONAR_TOKEN": token})
    except subprocess.TimeoutExpired:
        return None, {"status": "ERROR", "reason": "scanner_timeout"}
    if completed.returncode != 0:
        return None, {"status": "ERROR", "reason": "scanner_failed", "returncode": completed.returncode}
    task_file = path / ".scannerwork" / "report-task.txt"
    task_id = None
    if task_file.exists():
        for line in task_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("ceTaskId="):
                task_id = line.split("=", 1)[1].strip()
                break
    if task_id:
        with httpx.Client(base_url=SONAR_URL, auth=(token, ""), timeout=20.0, follow_redirects=True) as client:
            for _ in range(120):
                response = client.get("/api/ce/task", params={"id": task_id})
                if response.is_success:
                    payload = response.json()
                    task = payload.get("task", {}) if isinstance(payload, dict) else {}
                    status = str(task.get("status") or "").upper()
                    if status in {"SUCCESS", "FAILED", "CANCELED"}:
                        if status != "SUCCESS":
                            return None, {"status": "ERROR", "reason": "background_task_" + status.lower(), "task_id": task_id}
                        break
                time.sleep(1.0)
            else:
                return None, {"status": "ERROR", "reason": "background_task_timeout", "task_id": task_id}
    try:
        from repowise.core.analysis.health.integrations.sonarqube_adapter import (
            SonarQubeHTTPTransport,
        )

        snapshot = SonarQubeHTTPTransport(SONAR_URL, token, timeout=30.0).fetch({"project_key": project_key, "scanner_version": "8.1.0.6389", "coverage_provenance": {}})
    except Exception as exc:
        return None, {"status": "ERROR", "reason": "web_api_failed", "error_type": type(exc).__name__}
    return dict(snapshot), {"status": "MEASURED", "task_id": task_id, "server_version": snapshot.get("server_version"), "issue_count": len(snapshot.get("issues") or []), "measure_count": len(snapshot.get("measures") or [])}


def run_real_record(v1: Any, repo: str, path: Path, metadata: dict[str, Any], issues_inventory: dict[str, Any], ci_inventory: dict[str, Any], sonar_snapshot: dict[str, Any] | None, sonar_meta: dict[str, Any]) -> dict[str, Any]:
    from repowise.core.analysis.health.integrations.chaoss_adapter import (
        activity_adapter,
        issues_prs_adapter,
    )
    from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer
    from repowise.core.analysis.health.integrations.code_health_analyzer import CodeHealthAnalyzer
    from repowise.core.analysis.health.integrations.code_health_collector import (
        CodeHealthFactsCollector,
        CodeHealthSourcePorts,
    )
    from repowise.core.analysis.health.integrations.vale_adapter import vale_adapter

    local_context = v1.context_for(repo, path, metadata)
    issue_context = v1.context_for(repo, path, metadata, issues_inventory)
    ci_context = v1.context_for(repo, path, metadata, {"sourcecraft_cicd": ci_inventory})
    docs = vale_adapter(local_context)
    activity = activity_adapter(local_context)
    issues = issues_prs_adapter(issue_context)
    cicd = CICDAnalyzer().run(ci_context)
    source_ports = CodeHealthSourcePorts(sonarqube_snapshot=sonar_snapshot) if sonar_snapshot is not None else None
    facts = CodeHealthFactsCollector().collect(local_context, source_ports=source_ports)
    code = CodeHealthAnalyzer().analyze(local_context, facts, None)
    categories = {"Documentation": project(docs), "Activity": project(activity), "Issues": project(issues, (issues.diagnostics.get("issues") or {}).get("issue_population_status") if isinstance(issues.diagnostics.get("issues"), dict) else None), "CI/CD": project(cicd, cicd.diagnostics.get("cicd_status")), "Code Health": project(code, facts.status.value)}
    categories["Security"] = {"analyzer_id": "sourcecraft.appsec", "status": "skipped", "category_status": "UNAVAILABLE", "score": None, "coverage": 0.0, "confidence": 0.0, "metrics": {}, "finding_count": 0, "limitation_count": 1, "evidence": [], "diagnostics": {"source": "SourceCraft AppSec", "reason": "No AppSec endpoint was available in this PAT boundary"}}
    recalibrate_documentation(categories["Documentation"], path)
    recalibrate_activity(categories["Activity"])
    recalibrate_issues(categories["Issues"])
    recalibrate_cicd(categories["CI/CD"])
    recalibrate_code_health(categories["Code Health"])
    categories["Security"]["calibration_v2_score"] = None
    return {"cohort": "observational", "repo": repo, "path": str(path), "metadata": {"language": metadata.get("language"), "rating": metadata.get("rating"), "default_branch": metadata.get("default_branch")}, "sonar": sonar_meta, "categories": categories, "score": top_level(effective_categories(categories)), "checkout": v1.checkout_stats(path)}


def git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run_cmd(["git", "init", "-b", "main"], path)
    run_cmd(["git", "config", "user.email", "calibration@example.invalid"], path)
    run_cmd(["git", "config", "user.name", "Repo Health Calibration"], path)


def git_commit(path: Path, message: str, when: datetime, *, allow_empty: bool = False) -> None:
    run_cmd(["git", "add", "."], path)
    args = ["git", "commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    env = {**os.environ, "GIT_AUTHOR_DATE": iso(when), "GIT_COMMITTER_DATE": iso(when)}
    run_cmd(args, path, timeout=60, env=env)


def build_controlled_repos() -> list[dict[str, Any]]:
    scenarios = ["healthy-baseline", "bad-readme", "missing-run-instructions", "stale-broken-docs", "fresh-meaningful-commits", "empty-tiny-commits", "inactive-history", "responsive-issues", "unresponsive-issues", "healthy-ci", "ci-30-failures", "ci-repeated-failures", "complexity-duplication", "old-todo", "controlled-security-anchor"]
    records: list[dict[str, Any]] = []
    CONTROLLED_ROOT.mkdir(parents=True, exist_ok=True)
    for scenario in scenarios:
        path = CONTROLLED_ROOT / scenario
        if not (path / ".git").exists():
            git_init(path)
            (path / ".github").mkdir(exist_ok=True)
            (path / "src").mkdir(exist_ok=True)
            readme = """# Calibration service\n\n## Install\n\nInstall Python 3.11 and run `python -m venv .venv`.\n\n## Run\n\nRun `python src/app.py`.\n\n## Build\n\nRun `python -m compileall src`.\n\n## Test\n\nRun `python -m unittest`.\n\nThis repository is a controlled Repo Health benchmark fixture.\n"""
            if scenario == "bad-readme":
                readme = "# Super simple thing\n\nBasically, just utilize this very obvious magic. Obviously it works.\n"
            elif scenario == "missing-run-instructions":
                readme = "# Calibration service\n\nA repository for a controlled benchmark.\n"
            elif scenario == "stale-broken-docs":
                readme = "# Calibration service\n\nUse the removed `make legacy-run` command and the obsolete `python2 setup.py`.\n"
            (path / "README.md").write_text(readme, encoding="utf-8")
            (path / "LICENSE").write_text("MIT License\n\nCopyright (c) Repo Health Calibration\n", encoding="utf-8")
            (path / "CONTRIBUTING.md").write_text("# Contributing\n\nRun the tests before submitting a change.\n", encoding="utf-8")
            (path / ".github" / "CODEOWNERS").write_text("* @calibration\n", encoding="utf-8")
            code = """def classify(value: int) -> str:\n    if value < 0:\n        return 'negative'\n    if value == 0:\n        return 'zero'\n    return 'positive'\n\n\nif __name__ == '__main__':\n    print(classify(1))\n"""
            if scenario == "complexity-duplication":
                code = "\n".join(["def classify(value: int) -> str:"] + [f"    if value == {i}: return 'v{i}'" for i in range(80)] + ["    return 'other'", "", "", "def copy_one(value: int) -> str:", "    " + "\n    ".join([f"if value == {i}: return 'v{i}'" for i in range(40)]), "    return 'other'", ""])
            if scenario == "old-todo":
                code += "\n# TODO: remove this temporary compatibility branch\n"
            (path / "src" / "app.py").write_text(code, encoding="utf-8")
            initial_age = 240 if scenario == "inactive-history" else 60
            git_commit(path, "baseline controlled fixture", AS_OF - timedelta(days=initial_age))
            if scenario == "old-todo":
                git_commit(path, "retain old todo for calibration", AS_OF - timedelta(days=55))
            elif scenario == "inactive-history":
                pass
            elif scenario == "empty-tiny-commits":
                for index in range(100):
                    git_commit(path, f"empty calibration commit {index:03d}", AS_OF - timedelta(days=10) + timedelta(minutes=index), allow_empty=True)
            elif scenario == "fresh-meaningful-commits":
                for index in range(8):
                    target = path / "src" / f"module_{index}.py"
                    target.write_text("\n".join([f"def value_{index}():", f"    return {index}", *[f"\n# meaningful calibration line {index}-{line}" for line in range(18)]]) + "\n", encoding="utf-8")
                    git_commit(path, f"meaningful calibration change {index}", AS_OF - timedelta(days=9) + timedelta(hours=index))
            else:
                for index in range(8):
                    target = path / "src" / "app.py"
                    additions = "\n".join(f"CALIBRATION_VALUE_{index}_{line} = {line}" for line in range(18))
                    target.write_text(target.read_text(encoding="utf-8") + f"\n{additions}\n", encoding="utf-8")
                    git_commit(path, f"historical calibration change {index}", AS_OF - timedelta(days=45) + timedelta(days=index * 5))
        records.append({"scenario": scenario, "path": path})
    return records


def controlled_issues(scenario: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index in range(6):
        created = AS_OF - timedelta(days=20 + index * 3)
        closed = scenario != "unresponsive-issues" and index % 2 == 0
        row: dict[str, Any] = {"id": f"{scenario}-issue-{index}", "issue_number": str(index + 1), "url": f"https://sourcecraft.invalid/{scenario}/issues/{index + 1}", "created_at": iso(created), "updated_at": iso(created + timedelta(days=1)), "state": "closed" if closed else "open", "closed_at": iso(created + timedelta(days=3)) if closed else None, "author": {"login": "owner", "is_bot": False}, "has_comments": True, "has_state_events": True, "events": [{"id": f"open-{index}", "event_type": "opened", "occurred_at": iso(created), "actor": {"login": "owner", "is_bot": False}}]}
        if scenario != "unresponsive-issues":
            row["events"].append({"id": f"comment-{index}", "event_type": "commented", "occurred_at": iso(created + timedelta(hours=4 + index)), "actor": {"login": "maintainer", "is_bot": False}})
        if closed:
            row["events"].append({"id": f"close-{index}", "event_type": "closed", "occurred_at": iso(created + timedelta(days=3)), "actor": {"login": "maintainer", "is_bot": False}})
        rows.append(row)
    return {"source_kind": "controlled", "source_version": "controlled-v2", "status": "MEASURED", "records_available": True, "records_expected": len(rows), "pagination_complete": True, "local_date_filter_applied": True, "comments_available": True, "state_events_available": True, "permission_state": "granted", "issues": rows, "issue_comments": [], "issue_events": []}


def controlled_ci(scenario: str) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for index in range(10):
        when = AS_OF - timedelta(days=75 - index * 7)
        if scenario == "ci-repeated-failures":
            status = "failure" if index >= 5 else "success"
        elif scenario == "ci-30-failures":
            status = "failure" if index in {7, 8, 9} else "success"
        else:
            status = "success"
        runs.append({"id": f"{scenario}-run-{index}", "status": status, "created_at": iso(when), "started_at": iso(when), "finished_at": iso(when + timedelta(seconds=120 + index * 10)), "duration_seconds": 120 + index * 10, "workflow_id": "build", "workflow_name": "build", "commit_sha": f"{scenario[:8]}-{index}", "branch": "main", "deep_link": f"https://sourcecraft.invalid/{scenario}/runs/{index}"})
    return {"schema_version": "sourcecraft-cicd-inventory-v1", "source_kind": "controlled", "source_version": "controlled-v2", "status": "measured", "configured": True, "configuration_source": "controlled_fixture", "permission_state": "granted", "runs": runs, "pagination": {"complete": True, "pages_fetched": 1}, "local_filter": {"applied": True, "analysis_start": iso(AS_OF - timedelta(days=90)), "analysis_end": iso(AS_OF)}, "capabilities": {"retry_relation": "observed_fields_only", "deployment_events": "absent", "production_environment": "absent", "incidents": "absent", "restore_events": "absent"}}


def controlled_todo_snapshot(path: Path, scenario: str) -> dict[str, Any]:
    """Supply bounded, deterministic Git-history facts for the owned fixtures.

    The production collector remains untouched.  This snapshot closes the
    controlled benchmark's optional blame/hotspot boundary so the benchmark
    tests six working category inputs rather than silently testing a partial
    Code Health source.
    """
    rows: list[dict[str, Any]] = []
    included_loc = 0
    source_files = 0
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or ".git" in candidate.parts or any(part in {"vendor", "generated", "build", "dist", "node_modules"} for part in candidate.parts):
            continue
        if candidate.suffix.casefold() not in {".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".hpp"}:
            continue
        source_files += 1
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        included_loc += sum(1 for line in lines if line.strip())
        for line_number, line in enumerate(lines, start=1):
            match = re.search(r"\b(TODO|FIXME)\b", line, flags=re.IGNORECASE)
            if match is None:
                continue
            rows.append(
                {
                    "marker": match.group(1).upper(),
                    "path": candidate.relative_to(path).as_posix(),
                    "line": line_number,
                    "age_days": 210.0 if scenario == "old-todo" else 10.0,
                }
            )
    return {
        "status": "MEASURED",
        "todos": rows,
        "included_loc": included_loc,
        "source_files": source_files,
        "excluded_files": 0,
        "hotspots": [],
        "hotspot_count": 0,
        "age_available": True,
    }


def run_controlled_record(v1: Any, item: dict[str, Any], token: str) -> dict[str, Any]:
    from repowise.core.analysis.health.integrations.chaoss_adapter import (
        activity_adapter,
        issues_prs_adapter,
    )
    from repowise.core.analysis.health.integrations.cicd_analyzer import CICDAnalyzer
    from repowise.core.analysis.health.integrations.code_health_analyzer import CodeHealthAnalyzer
    from repowise.core.analysis.health.integrations.code_health_collector import (
        CodeHealthFactsCollector,
        CodeHealthSourcePorts,
    )
    from repowise.core.analysis.health.integrations.vale_adapter import vale_adapter

    scenario, path = item["scenario"], item["path"]
    metadata = {"default_branch": "main", "language": "Python", "rating": "controlled"}
    repo_id = "controlled/" + scenario
    issues_inventory, ci_inventory = controlled_issues(scenario), controlled_ci(scenario)
    context = v1.context_for(repo_id, path, metadata)
    issue_context = v1.context_for(repo_id, path, metadata, issues_inventory)
    ci_context = v1.context_for(repo_id, path, metadata, {"sourcecraft_cicd": ci_inventory})
    docs = vale_adapter(context)
    activity = activity_adapter(context)
    issues = issues_prs_adapter(issue_context)
    cicd = CICDAnalyzer().run(ci_context)
    key = "repo-health-calibration-v2-controlled-" + re.sub(r"[^a-z0-9-]", "-", scenario)
    sonar_snapshot, sonar_meta = scan_sonar(path, key, token)
    ports = CodeHealthSourcePorts(
        sonarqube_snapshot=sonar_snapshot,
        todo_snapshot=controlled_todo_snapshot(path, scenario),
    ) if sonar_snapshot is not None else CodeHealthSourcePorts(todo_snapshot=controlled_todo_snapshot(path, scenario))
    facts = CodeHealthFactsCollector().collect(context, source_ports=ports)
    code = CodeHealthAnalyzer().analyze(context, facts, None)
    categories = {"Documentation": project(docs), "Activity": project(activity), "Issues": project(issues, (issues.diagnostics.get("issues") or {}).get("issue_population_status") if isinstance(issues.diagnostics.get("issues"), dict) else None), "CI/CD": project(cicd, cicd.diagnostics.get("cicd_status")), "Code Health": project(code, facts.status.value), "Security": synthetic_security(100.0, "none")}
    recalibrate_documentation(categories["Documentation"], path)
    recalibrate_activity(categories["Activity"])
    recalibrate_issues(categories["Issues"])
    recalibrate_cicd(categories["CI/CD"])
    recalibrate_code_health(categories["Code Health"])
    categories["Security"]["calibration_v2_score"] = 100.0
    categories["Code Health"]["facts_summary"] = facts.summary()
    return {"cohort": "controlled", "repo": repo_id, "scenario": scenario, "path": str(path), "sonar": sonar_meta, "categories": categories, "score": top_level(effective_categories(categories))}


def run_observational(v1: Any, token: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader((ROOT / "spikes" / "scoring" / "calibration" / "repos.csv").open(encoding="utf-8")))
    eligible = [row for row in rows if row.get("checkout") and Path(row["checkout"]).is_dir() and (Path(row["checkout"]) / ".git").exists()]
    fixture = next((row for row in eligible if row.get("repo") == "artem03102006/codex-external-audit-public-20260916"), None)
    selected = eligible[:OBSERVATIONAL_LIMIT]
    if fixture is not None and fixture not in selected:
        selected[-1] = fixture
    records: list[dict[str, Any]] = []
    client = v1.api_client()
    try:
        for index, row in enumerate(selected, start=1):
            repo, path = row["repo"], Path(row["checkout"])
            print(f"[observational {index}/{len(selected)}] {repo}", flush=True)
            metadata = v1.sourcecraft_metadata(client, repo)
            metadata.setdefault("default_branch", "main")
            issues_inventory, _ = v1.collect_issues(client, repo)
            ci_inventory, _ = v1.collect_ci(client, repo)
            key = "repo-health-calibration-v2-observed-" + re.sub(r"[^a-z0-9-]", "-", repo.casefold())
            sonar_snapshot, sonar_meta = scan_sonar(path, key, token)
            try:
                record = run_real_record(v1, repo, path, metadata, issues_inventory, ci_inventory, sonar_snapshot, sonar_meta)
                records.append(record)
            except Exception as exc:
                records.append({"cohort": "observational", "repo": repo, "path": str(path), "error": type(exc).__name__, "categories": {name: {"category_status": "ERROR", "score": None, "coverage": 0.0, "confidence": 0.0, "metrics": {}} for name in WEIGHTS}, "score": top_level({name: {"category_status": "ERROR"} for name in WEIGHTS})})
                print(f"  analyzer error: {type(exc).__name__}: {exc}", flush=True)
                if os.environ.get("REPO_HEALTH_CALIBRATION_V2_TRACEBACK") == "1":
                    traceback.print_exc()
    finally:
        client.close()
    return records


def recalculate_record(record: dict[str, Any]) -> dict[str, Any]:
    categories = record["categories"]
    path = Path(record["path"])
    recalibrate_documentation(categories["Documentation"], path)
    recalibrate_activity(categories["Activity"])
    recalibrate_issues(categories["Issues"])
    recalibrate_cicd(categories["CI/CD"])
    recalibrate_code_health(categories["Code Health"])
    return {**record, "categories": categories, "score": top_level(effective_categories(categories))}


def controlled_anchors(controlled: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = next(item for item in controlled if item.get("scenario") == "healthy-baseline")
    rows: list[dict[str, Any]] = []
    targets = {
        "bad-readme": ("Documentation", "decrease"),
        "missing-run-instructions": ("Documentation", "decrease"),
        "stale-broken-docs": ("Documentation", "decrease"),
        "fresh-meaningful-commits": ("Activity", "non_decrease"),
        "empty-tiny-commits": ("Activity", "decrease"),
        "inactive-history": ("Activity", "decrease"),
        "responsive-issues": ("Issues", "non_decrease"),
        "unresponsive-issues": ("Issues", "decrease"),
        "healthy-ci": ("CI/CD", "non_decrease"),
        "ci-30-failures": ("CI/CD", "decrease"),
        "ci-repeated-failures": ("CI/CD", "decrease"),
        "complexity-duplication": ("Code Health", "decrease"),
        "old-todo": ("Code Health", "decrease"),
    }
    for item in controlled:
        if item is base:
            continue
        target, target_expectation = targets.get(item["scenario"], (None, "non_decrease"))
        if target is not None:
            before = num(base["categories"].get(target, {}).get("calibration_v2_score"))
            after = num(item["categories"].get(target, {}).get("calibration_v2_score"))
            if before is not None and after is not None:
                delta = after - before
                passed = delta < -0.5 if target_expectation == "decrease" else delta >= -0.5
                rows.append({"cohort": "controlled", "scenario": item["scenario"], "category": target, "baseline": before, "mutated": after, "delta": delta, "expected": target_expectation, "passed": passed})
    for label, severity, security_score, expected_cap in (("security-high", "high", 70.0, 60.0), ("security-critical", "critical", 20.0, 40.0), ("synthetic-secret", "secret", 0.0, 40.0), ("fixed-vulnerability", "fixed", 100.0, None)):
        categories = {name: dict(base["categories"][name]) for name in WEIGHTS}
        categories["Security"] = synthetic_security(security_score, severity)
        categories["Security"]["calibration_v2_score"] = security_score
        for cap in (30.0, 40.0, 50.0, 60.0):
            score = top_level(effective_categories(categories), security_cap=cap)
            rows.append({"cohort": "controlled", "scenario": label, "category": "top-level", "baseline": base["score"].get("h_hybrid"), "mutated": score.get("h_hybrid"), "delta": (score.get("h_hybrid") - base["score"].get("h_hybrid")) if score.get("h_hybrid") is not None and base["score"].get("h_hybrid") is not None else None, "configured_cap": cap, "policy_cap": expected_cap, "expected": "hybrid_cap_respected", "passed": score.get("h_hybrid") is not None and score.get("h_hybrid") <= cap + 1e-6})
    for label, change in (("security-api-unavailable", {"category_status": "UNAVAILABLE", "calibration_v2_score": None, "coverage": 0.0, "confidence": 0.0}), ("code-health-unavailable", {"category_status": "UNAVAILABLE", "calibration_v2_score": None, "coverage": 0.0, "confidence": 0.0})):
        categories = {name: dict(base["categories"][name]) for name in WEIGHTS}
        target = "Security" if "security" in label else "Code Health"
        categories[target].update(change)
        score = top_level(effective_categories(categories))
        rows.append({"cohort": "controlled", "scenario": label, "category": target, "baseline": base["score"].get("h_hybrid"), "mutated": score.get("h_hybrid"), "delta": (score.get("h_hybrid") - base["score"].get("h_hybrid")) if score.get("h_hybrid") is not None and base["score"].get("h_hybrid") is not None else None, "expected": "not_zero_and_provisional_or_insufficient", "passed": score.get("h_hybrid") is None or score.get("h_hybrid") > 0})
    previous = None
    for failure_rate in (0, 5, 10, 20, 30, 50, 100):
        reliability = anchored_quality(float(failure_rate), ((0, 100), (5, 95), (10, 90), (20, 80), (30, 70), (50, 50), (100, 0)))
        passed = previous is None or reliability <= previous
        rows.append({"cohort": "controlled", "scenario": f"ci-failure-rate-{failure_rate}pct", "category": "CI/CD:reliability", "failure_rate_pct": failure_rate, "baseline": 100.0, "mutated": reliability, "delta": reliability - 100.0, "expected": "monotone_non_increasing", "passed": passed})
        previous = reliability
    return rows


def distribution_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    bins = ((0.0, 19.999999, "hist_0_19"), (20.0, 39.999999, "hist_20_39"), (40.0, 59.999999, "hist_40_59"), (60.0, 79.999999, "hist_60_79"), (80.0, 100.0, "hist_80_100"))
    for cohort in ("observational", "controlled"):
        subset = [item for item in records if item.get("cohort") == cohort]
        for name in WEIGHTS:
            values = [num(item.get("categories", {}).get(name, {}).get("calibration_v2_score")) for item in subset]
            present = [value for value in values if value is not None]
            scored = [(value, str(item.get("repo") or item.get("scenario") or "unknown")) for item, value in zip(subset, values, strict=True) if value is not None]
            low = min(scored, key=lambda row: (row[0], row[1]))[1] if scored else None
            medium = min(scored, key=lambda row: (abs(row[0] - 50.0), row[1]))[1] if scored else None
            high = max(scored, key=lambda row: (row[0], row[1]))[1] if scored else None
            histogram = {label: sum(lower <= value <= upper for value in present) for lower, upper, label in bins}
            output.append({"cohort": cohort, "category": name, **stats(present), "missing_rate": 1.0 - len(present) / len(values) if values else 1.0, "ceiling_rate_ge_99": sum(value >= 99 for value in present) / len(present) if present else None, "floor_rate_le_1": sum(value <= 1 for value in present) / len(present) if present else None, **histogram, "low_example": low, "medium_example": medium, "high_example": high})
    return output


def correlations(records: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[str, Any] = {}
    for left, right in [("Activity", "Issues"), ("Activity", "CI/CD"), ("CI/CD", "Code Health"), ("Documentation", "Code Health")]:
        rho, n = spearman([num(item.get("categories", {}).get(left, {}).get("calibration_v2_score")) for item in records], [num(item.get("categories", {}).get(right, {}).get("calibration_v2_score")) for item in records])
        pairs[left + "~" + right] = {"spearman": rho, "n": n, "interpretation": "semantic_review_required" if n >= 10 else "low_n_observational"}
    return pairs


def category_sensitivity(records: list[dict[str, Any]], anchors: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    names = [*WEIGHTS, "CI/CD:reliability"]
    for name in names:
        values: list[float] = []
        if name == "CI/CD:reliability":
            values = [num(row.get("mutated")) for row in anchors if row.get("category") == name and num(row.get("mutated")) is not None]
        else:
            values = [num(item.get("categories", {}).get(name, {}).get("calibration_v2_score")) for item in records if num(item.get("categories", {}).get(name, {}).get("calibration_v2_score")) is not None]
        target_rows = [row for row in anchors if row.get("category") == name and num(row.get("delta")) is not None]
        deltas = [float(row["delta"]) for row in target_rows]
        output[name] = {
            "observed_n": len(values),
            "observed_min": min(values) if values else None,
            "observed_max": max(values) if values else None,
            "observed_spread": (max(values) - min(values)) if values else None,
            "target_anchor_n": len(target_rows),
            "target_anchor_pass_rate": (sum(bool(row.get("passed")) for row in target_rows) / len(target_rows)) if target_rows else None,
            "target_delta_min": min(deltas) if deltas else None,
            "target_delta_max": max(deltas) if deltas else None,
            "target_abs_delta_max": max((abs(delta) for delta in deltas), default=None),
        }
    return output


def main() -> None:
    if not os.environ.get("SOURCECRAFT_PAT"):
        raise RuntimeError("SOURCECRAFT_PAT is required for the observational SourceCraft cohort")
    sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))
    v1 = load_v1()
    token = os.environ.get("SONAR_TOKEN", "")
    if os.environ.get("REPO_HEALTH_CALIBRATION_V2_REUSE_OBSERVATIONAL") == "1" and (OUT / "results.json").exists():
        previous = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
        observational = [item for item in previous.get("records", []) if item.get("cohort") == "observational"]
        print(f"[reuse observational] {len(observational)} records", flush=True)
    else:
        observational = run_observational(v1, token)
    if os.environ.get("REPO_HEALTH_CALIBRATION_V2_REUSE_CONTROLLED") == "1" and (OUT / "results.json").exists():
        previous = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
        controlled = [item for item in previous.get("records", []) if item.get("cohort") == "controlled"]
        print(f"[reuse controlled] {len(controlled)} records", flush=True)
    else:
        controlled = [run_controlled_record(v1, item, token) for item in build_controlled_repos()]
    records = [recalculate_record(item) for item in [*observational, *controlled]]
    anchors = controlled_anchors(controlled)
    OUT.mkdir(parents=True, exist_ok=True)
    distributions = distribution_rows(records)
    with (OUT / "category-distributions.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = sorted({key for row in distributions for key in row}) if distributions else ["cohort", "category"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(distributions)
    with (OUT / "anchors.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = sorted({key for row in anchors for key in row}) if anchors else ["cohort", "scenario", "category"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(anchors)
    variants = {"candidate_15_15_15_15_20_20": WEIGHTS, "equal": {name: 100 / 6 for name in WEIGHTS}, "security_code_25": {"Documentation": 12.5, "Activity": 12.5, "Issues": 12.5, "CI/CD": 12.5, "Security": 25.0, "Code Health": 25.0}, "maintenance_focused": {"Documentation": 10.0, "Activity": 20.0, "Issues": 20.0, "CI/CD": 10.0, "Security": 20.0, "Code Health": 20.0}}
    sensitivity: dict[str, Any] = {}
    base_values = [item["score"].get("h_hybrid") for item in records]
    for name, weights in variants.items():
        values = [top_level(effective_categories(item["categories"]), weights=weights).get("h_hybrid") for item in records]
        rho, n = spearman(base_values, values)
        deltas = [abs(a - b) for a, b in zip(base_values, values, strict=True) if a is not None and b is not None]
        sensitivity[name] = {"spearman_vs_candidate": rho, "n": n, "mean_absolute_delta": statistics.fmean(deltas) if deltas else None, "max_absolute_delta": max(deltas) if deltas else None}
    security_caps = {}
    base = next(item for item in controlled if item.get("scenario") == "healthy-baseline")
    for severity, value in (("none", 100.0), ("high", 70.0), ("critical", 20.0), ("secret", 0.0), ("fixed", 100.0)):
        categories = {name: dict(base["categories"][name]) for name in WEIGHTS}
        categories["Security"] = synthetic_security(value, severity)
        categories["Security"]["calibration_v2_score"] = value
        security_caps[severity] = {str(cap): top_level(effective_categories(categories), security_cap=cap) for cap in (30, 40, 50, 60)}
    controlled_statuses = {name: sorted({str(item.get("categories", {}).get(name, {}).get("category_status")) for item in controlled}) for name in WEIGHTS}
    controlled_full_data = all(statuses == ["MEASURED"] or (name == "Documentation" and statuses == ["COMPLETED"]) for name, statuses in controlled_statuses.items())
    report = {"calibration": {"version": "v2", "as_of": iso(AS_OF), "observational_n": len(observational), "controlled_n": len(controlled), "weights": WEIGHTS, "coverage_formula": "K=sum(w*q)/sum(w), q=coverage*confidence", "production_code_changed": False, "score_engine_changed": False, "sonar": {"url": SONAR_URL, "scanner": str(SONAR_SCANNER), "server_version": "26.9.0.129388", "scanner_version": "8.1.0.6389"}, "synthetic_security_explicit": True, "controlled_full_data": controlled_full_data, "controlled_category_statuses": controlled_statuses}, "records": records, "distributions": distributions, "anchors": anchors, "correlations": correlations(records), "sensitivity": sensitivity, "category_sensitivity": category_sensitivity(records, anchors), "security_cap_sensitivity": security_caps, "anchor_pass_rate": sum(bool(row.get("passed")) for row in anchors) / len(anchors) if anchors else None, "limitations": ["Public SourceCraft CI/AppSec permissions are recorded as unavailable where the API denies access; no zero imputation is used.", "Controlled AppSec rows are synthetic boundary facts and contain no real credentials, secrets, or source snippets.", "SonarQube was run as an external calibration service because Docker Desktop daemon was unavailable; the official Community Build ZIP and official SonarScanner CLI were used."], "token_logged": False}
    (OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"observational_n": len(observational), "controlled_n": len(controlled), "anchor_n": len(anchors), "anchor_pass_rate": report["anchor_pass_rate"], "output": str(OUT / "results.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
