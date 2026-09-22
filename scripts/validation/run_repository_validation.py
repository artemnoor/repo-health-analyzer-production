"""Run one public GitHub repository through the production health pipeline.

This module is deliberately outside ``src/repo_health``.  It observes the
production contracts, writes redacted evidence projections, and never changes
the analyzer or score implementations.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog

from repo_health.config import RuntimeConfig
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.persistence import SQLitePersistence
from repo_health.runtime import build_production_runtime

log = structlog.get_logger("repo_health.validation")

_HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_SECRET_VALUE = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+|(?:token|password|secret|api[_-]?key)\s*[:=]\s*)([^\s,;]+)"
)
_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
_ARTIFACT_SUFFIXES = (".zip", ".tgz", ".tar", ".tar.gz", ".7z", ".rar")

SOURCECRAFT_ONLY_CATEGORIES = {"issues", "cicd", "security"}
VALIDATION_VALE_CONFIG = Path(__file__).resolve().parent / "vale" / ".vale.ini"
CATEGORY_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "documentation": ("Vale", ("vale",)),
    "activity": ("PyDriller/Git", ("git", "pydriller")),
    "issues": ("SourceCraft Issues REST", ("sourcecraft",)),
    "cicd": ("SourceCraft CI/CD REST", ("sourcecraft",)),
    "security": ("SourceCraft AppSec REST", ("sourcecraft",)),
    "code_health": ("SonarQube/git-sizer/Git/TODO-history", ("git.todo-history", "git-sizer", "sonarqube")),
}
POLICY_VERSIONS = {
    "documentation": "documentation-calibration-v2",
    "activity": "activity-calibration-v2",
    "issues": "issues-calibration-v2",
    "cicd": "cicd-calibration-v2",
    "security": "security-appsec-v1",
    "code_health": "code-health-calibration-v2",
}


@dataclass(frozen=True, slots=True)
class RepositorySpec:
    slug: str
    name: str
    url: str
    repository_type: str
    hypothesis: str


REPOSITORY_MANIFEST: tuple[RepositorySpec, ...] = (
    RepositorySpec(
        "mvp-food",
        "MVP_FOOD",
        "https://github.com/Artem336600/MVP_FOOD",
        "VERY_WEAK",
        "Tiny or nearly empty lower-bound control; should not receive health from absent evidence.",
    ),
    RepositorySpec(
        "freshly",
        "Freshly",
        "https://github.com/Artem336600/Freshly",
        "WEAK",
        "Small Python project with minimal documentation; tests small-clean-code overvaluation.",
    ),
    RepositorySpec(
        "todo",
        "TODO",
        "https://github.com/Artem336600/TODO",
        "MIXED",
        "Documentation should separate from older/smaller development activity.",
    ),
    RepositorySpec(
        "ocheredibm3",
        "Ocheredibm3",
        "https://github.com/artemnoor/Ocheredibm3",
        "MIXED",
        "Good instructions with a small history and a repository archive artifact observation.",
    ),
    RepositorySpec(
        "procsima-low-version",
        "Procsima-low_version-",
        "https://github.com/artemnoor/Procsima-low_version-",
        "MIXED",
        "Legacy/dirty repository used as a negative hygiene observation, not ground truth.",
    ),
    RepositorySpec(
        "two-cucumbersfloating",
        "Two-cucumbersfloating",
        "https://github.com/artemnoor/Two-cucumbersfloating",
        "ADVERSARIAL",
        "Polished documentation around little substantive product content.",
    ),
    RepositorySpec(
        "andromeda",
        "andromeda",
        "https://github.com/artemnoor/andromeda",
        "STRONG_USER",
        "Positive control with docs, gates, and active development history.",
    ),
    RepositorySpec(
        "codeslicer",
        "CodeSlicer",
        "https://github.com/Artem336600/CodeSlicer",
        "STRONG_USER",
        "Large mature user project; size must not be treated as an automatic penalty.",
    ),
    RepositorySpec(
        "repo-health-analyzer-production",
        "repo-health-analyzer-production",
        "https://github.com/artemnoor/repo-health-analyzer-production",
        "STRONG_USER",
        "Own positive control; never use it for automatic formula calibration.",
    ),
    RepositorySpec(
        "ruff",
        "ruff",
        "https://github.com/astral-sh/ruff",
        "GOLDEN_OSS",
        "Mature OSS positive control for documentation, activity, and code health.",
    ),
    RepositorySpec(
        "uv",
        "uv",
        "https://github.com/astral-sh/uv",
        "GOLDEN_OSS",
        "Mature active OSS large-repository handling control.",
    ),
    RepositorySpec(
        "fastapi",
        "fastapi",
        "https://github.com/fastapi/fastapi",
        "GOLDEN_OSS",
        "Mature Python project for comparison with user repositories.",
    ),
    RepositorySpec(
        "pydantic",
        "pydantic",
        "https://github.com/pydantic/pydantic",
        "GOLDEN_OSS",
        "Mature Python positive control for documentation/activity/code health.",
    ),
)


@dataclass(slots=True)
class CloneResult:
    status: str
    head_sha: str | None = None
    duration_ms: int = 0
    error: str | None = None
    return_code: int | None = None
    checkout_path: Path | None = field(default=None, repr=False)

    def public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "head_sha": self.head_sha,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "return_code": self.return_code,
        }


@dataclass(slots=True)
class TimingBreakdown:
    clone_ms: int = 0
    collection_ms: int = 0
    normalization_ms: int = 0
    analyzer_ms: int = 0
    score_engine_ms: int = 0
    total_ms: int = 0
    report_ms: int = 0
    source_ms: dict[str, int] = field(default_factory=dict)

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ValidationRunResult:
    spec: RepositorySpec
    outcome: str
    clone: CloneResult
    timings: TimingBreakdown
    capabilities: dict[str, dict[str, object]]
    inventory: dict[str, object]
    analysis: dict[str, object] | None = None
    determinism: dict[str, object] | None = None
    errors: list[dict[str, str]] = field(default_factory=list)

    def public_dict(self) -> dict[str, object]:
        return {
            "schema_version": "repo-health-validation-v1",
            "repository": asdict(self.spec),
            "outcome": self.outcome,
            "clone": self.clone.public_dict(),
            "timings_ms": self.timings.public_dict(),
            "capabilities": self.capabilities,
            "inventory": self.inventory,
            "analysis": self.analysis,
            "determinism": self.determinism,
            "errors": list(self.errors),
            "sourcecraft_validation_scope": {
                "provider": "github",
                "github_api_substitutions": False,
                "issues": "production SourceCraft Issues provider exists but is intentionally not exercised by this GitHub run",
                "cicd": "production SourceCraft CI/CD provider exists but is intentionally not exercised by this GitHub run",
                "security": "SourceCraft AppSec-only; not validated by this GitHub run",
            },
        }


class _TimedCollection:
    def __init__(self, delegate: Any, timings: TimingBreakdown) -> None:
        self._delegate = delegate
        self._timings = timings

    async def collect(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return await self._delegate.collect(*args, **kwargs)
        finally:
            self._timings.collection_ms = _elapsed_ms(started)
            self._timings.normalization_ms = max(
                0,
                self._timings.collection_ms - sum(self._timings.source_ms.values()),
            )


class _TimedCollector:
    def __init__(self, delegate: Any, timings: TimingBreakdown) -> None:
        self._delegate = delegate
        self._timings = timings
        self.source_id = delegate.source_id

    async def collect(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = self._delegate.collect(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        finally:
            self._timings.source_ms[self.source_id] = _elapsed_ms(started)


class _TimedScoreEngine:
    def __init__(self, delegate: Any, timings: TimingBreakdown) -> None:
        self._delegate = delegate
        self._timings = timings

    def score(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return self._delegate.score(*args, **kwargs)
        finally:
            self._timings.score_engine_ms = _elapsed_ms(started)


class _TimedExecutor:
    def __init__(self, delegate: Any, timings: TimingBreakdown) -> None:
        self._delegate = delegate
        self._timings = timings

    async def execute_many(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return await self._delegate.execute_many(*args, **kwargs)
        finally:
            self._timings.analyzer_ms = _elapsed_ms(started)


def validate_manifest(manifest: tuple[RepositorySpec, ...] = REPOSITORY_MANIFEST) -> None:
    if len(manifest) != 13:
        raise ValueError(f"validation manifest must contain 13 repositories, found {len(manifest)}")
    slugs = [item.slug for item in manifest]
    urls = [item.url for item in manifest]
    if len(set(slugs)) != len(slugs):
        raise ValueError("validation manifest contains duplicate slugs")
    if len(set(urls)) != len(urls):
        raise ValueError("validation manifest contains duplicate URLs")
    for item in manifest:
        if not item.url.startswith("https://github.com/") or "://" in item.url.removeprefix("https://"):
            raise ValueError(f"validation URL is not a public GitHub URL: {item.url!r}")
        if any(marker in item.url.casefold() for marker in ("token", "password", "secret", "@")):
            raise ValueError(f"validation URL contains secret-like material: {item.url!r}")


def _validate_local_sonar_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("SonarQube validation endpoint must be a local localhost/loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("SonarQube validation endpoint must not contain credentials or query material")


def clone_repository(spec: RepositorySpec, checkout_root: Path, *, timeout_seconds: float = 600.0) -> CloneResult:
    """Clone one public repository without shell expansion or credential injection."""

    started = time.perf_counter()
    checkout_root.mkdir(parents=True, exist_ok=True)
    destination = checkout_root / spec.slug
    log.info("validation_clone_started", slug=spec.slug, timeout_seconds=timeout_seconds)
    if destination.exists():
        result = CloneResult(
            status="failed",
            duration_ms=_elapsed_ms(started),
            error="checkout destination already exists; use a new validation run directory",
        )
        log.warning("validation_clone_failed", slug=spec.slug, reason="destination_exists")
        return result
    try:
        git_prefix = ["git", "-c", "core.longpaths=true"] if os.name == "nt" else ["git"]
        completed = subprocess.run(
            [*git_prefix, "clone", "--no-tags", "--quiet", spec.url, str(destination)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = CloneResult(status="failed", duration_ms=_elapsed_ms(started), error="git clone timed out")
        log.warning("validation_clone_failed", slug=spec.slug, reason="timeout")
        return result
    except OSError as exc:
        result = CloneResult(
            status="failed", duration_ms=_elapsed_ms(started), error=f"git clone could not start: {type(exc).__name__}"
        )
        log.warning("validation_clone_failed", slug=spec.slug, reason=type(exc).__name__)
        return result
    if completed.returncode != 0:
        result = CloneResult(
            status="failed",
            duration_ms=_elapsed_ms(started),
            error=_redact_process_text(completed.stderr)[:512] or "git clone failed",
            return_code=completed.returncode,
        )
        log.warning("validation_clone_failed", slug=spec.slug, return_code=completed.returncode)
        return result
    try:
        head = subprocess.run(
            ["git", "-C", str(destination), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CloneResult(
            status="failed",
            duration_ms=_elapsed_ms(started),
            error=f"could not resolve cloned HEAD: {type(exc).__name__}",
        )
        log.warning("validation_clone_failed", slug=spec.slug, reason="head_resolution")
        return result
    head_sha = head.stdout.strip().lower()
    if head.returncode != 0 or not _HEX_SHA.fullmatch(head_sha):
        result = CloneResult(
            status="failed",
            duration_ms=_elapsed_ms(started),
            error="cloned repository did not produce an immutable HEAD SHA",
            return_code=head.returncode,
        )
        log.warning("validation_clone_failed", slug=spec.slug, reason="invalid_head")
        return result
    result = CloneResult(
        status="cloned",
        head_sha=head_sha,
        duration_ms=_elapsed_ms(started),
        return_code=0,
        checkout_path=destination,
    )
    log.info("validation_clone_finished", slug=spec.slug, head_sha=head_sha, duration_ms=result.duration_ms)
    return result


def validate_checkout(
    spec: RepositorySpec,
    clone: CloneResult,
    *,
    as_of: datetime,
    output_dir: Path | None = None,
    analysis_timeout_seconds: float = 900.0,
    enable_sonarqube: bool = False,
    sonar_url: str | None = None,
    sonar_token: str | None = None,
) -> ValidationRunResult:
    """Run the canonical production pipeline for one already-cloned checkout."""

    timings = TimingBreakdown(clone_ms=clone.duration_ms)
    inventory = collect_inventory(clone.checkout_path) if clone.checkout_path else {}
    if clone.status != "cloned" or clone.checkout_path is None:
        return ValidationRunResult(
            spec=spec,
            outcome="clone_failed",
            clone=clone,
            timings=timings,
            capabilities={},
            inventory=inventory,
            errors=[{"phase": "clone", "type": clone.error or "clone_failed"}],
        )
    started = time.perf_counter()
    log.info("validation_analysis_started", slug=spec.slug, head_sha=clone.head_sha)
    runtime = None
    capabilities: dict[str, dict[str, object]] = {}
    try:
        environment = dict(os.environ)
        # GitHub validation must never send arbitrary public repository IDs to
        # SourceCraft. SonarQube is opt-in for a local validation server only;
        # its token is kept in the process environment and never enters the
        # validation artifacts.
        for key in ("SOURCECRAFT_URL", "SOURCECRAFT_TOKEN", "SONAR_URL", "SONAR_TOKEN"):
            environment.pop(key, None)
        environment.update(
            {
                "REPO_HEALTH_DB": ":memory:",
                "REPO_HEALTH_CHECKOUT_ROOT": str(clone.checkout_path),
            }
        )
        if VALIDATION_VALE_CONFIG.is_file():
            environment["VALE_CONFIG_PATH"] = str(VALIDATION_VALE_CONFIG)
        if enable_sonarqube:
            if not sonar_url or not sonar_token:
                raise ValueError("SonarQube validation requires --sonar-url and SONAR_TOKEN")
            _validate_local_sonar_url(sonar_url)
            environment["SONAR_URL"] = sonar_url
            environment["SONAR_TOKEN"] = sonar_token
        config = RuntimeConfig.from_environment(environment)
        runtime = build_production_runtime(config, mode="api", persistence=SQLitePersistence(":memory:"))
        capabilities = runtime.public_capabilities()
        runtime.orchestrator.collection.collectors = tuple(
            _TimedCollector(collector, timings) for collector in runtime.orchestrator.collection.collectors
        )
        runtime.orchestrator.collection = _TimedCollection(runtime.orchestrator.collection, timings)
        runtime.orchestrator.executor = _TimedExecutor(runtime.orchestrator.executor, timings)
        runtime.orchestrator.score_engine = _TimedScoreEngine(runtime.orchestrator.score_engine, timings)
        repository = RepositoryRef(
            # SonarQube project keys do not accept the slash in the public
            # provider/id notation. This validation-only key is stable and
            # leaves the URL/HEAD as the audit identity.
            repository_id=f"github.{spec.slug}",
            canonical_uri=spec.url,
            provider="github",
            ref="HEAD",
            head_sha=clone.head_sha,
        )
        request = AnalysisRequest(
            repository=repository,
            as_of=as_of,
            config_digest=config.digest(),
        )
        envelope = asyncio.run(
            asyncio.wait_for(
                runtime.orchestrator.analyze(request, checkout_path=clone.checkout_path),
                timeout=analysis_timeout_seconds,
            )
        )
        analysis = _analysis_payload(envelope, capabilities)
        outcome = "degraded" if analysis["status"]["state"] != "completed" else "completed"
        result = ValidationRunResult(
            spec=spec,
            outcome=outcome,
            clone=clone,
            timings=timings,
            capabilities=capabilities,
            inventory=inventory,
            analysis=analysis,
        )
    except TimeoutError:
        result = ValidationRunResult(
            spec=spec,
            outcome="analysis_failed",
            clone=clone,
            timings=timings,
            capabilities=capabilities,
            inventory=inventory,
            errors=[{"phase": "analysis", "type": "timeout"}],
        )
        log.warning("validation_analysis_failed", slug=spec.slug, error_type="timeout")
    except Exception as exc:
        result = ValidationRunResult(
            spec=spec,
            outcome="analysis_failed",
            clone=clone,
            timings=timings,
            capabilities=capabilities,
            inventory=inventory,
            errors=[
                {
                    "phase": "analysis",
                    "type": type(exc).__name__,
                    "detail": _redact_process_text(str(exc))[:512],
                }
            ],
        )
        log.warning(
            "validation_analysis_failed",
            slug=spec.slug,
            error_type=type(exc).__name__,
            error_detail=_redact_process_text(str(exc))[:512],
        )
    finally:
        timings.total_ms = max(timings.clone_ms, _elapsed_ms(started) + timings.clone_ms)
        if runtime is not None:
            runtime.close()
    log.info(
        "validation_analysis_finished",
        slug=spec.slug,
        outcome=result.outcome,
        category_count=len(result.analysis.get("categories", ())) if result.analysis else 0,
        total_ms=timings.total_ms,
    )
    return result


def collect_inventory(checkout_path: Path | None) -> dict[str, object]:
    if checkout_path is None or not checkout_path.is_dir():
        return {}
    paths = _tracked_paths(checkout_path)
    if not paths:
        paths = [path.relative_to(checkout_path).as_posix() for path in checkout_path.rglob("*") if path.is_file()]
    normalized = tuple(sorted(path.replace("\\", "/") for path in paths))
    source_files = [path for path in normalized if Path(path).suffix.casefold() in _SOURCE_EXTENSIONS]
    lower_names = {path.casefold() for path in normalized}
    artifact_paths = [
        path
        for path in normalized
        if path.casefold().endswith(_ARTIFACT_SUFFIXES) or Path(path).name.casefold() in {"old.html", "test.html"}
    ]
    total_bytes = 0
    for relative in normalized:
        with _suppress_os_error():
            total_bytes += (checkout_path / relative).stat().st_size
    return {
        "tracked_file_count": len(normalized),
        "source_file_count": len(source_files),
        "total_bytes": total_bytes,
        "readme_present": any(Path(path).name.casefold().startswith("readme") for path in normalized),
        "contributing_present": any(Path(path).name.casefold().startswith("contributing") for path in normalized),
        "license_present": any(Path(path).name.casefold().startswith("license") for path in normalized),
        "github_dir_present": any(path == ".github" or path.startswith(".github/") for path in normalized),
        "docs_dir_present": any(path == "docs" or path.startswith("docs/") for path in normalized),
        "artifact_paths": artifact_paths[:100],
        "artifact_count": len(artifact_paths),
        "inventory_limited": len(normalized) >= 100_000,
        "name_sample": list(normalized[:20]),
        "source_name_sample": source_files[:20],
        "lower_names_count": len(lower_names),
    }


def write_result(result: ValidationRunResult, output_dir: Path) -> tuple[Path, Path]:
    repositories_dir = output_dir / "repositories"
    repositories_dir.mkdir(parents=True, exist_ok=True)
    payload = result.public_dict()
    json_path = repositories_dir / f"{result.spec.slug}.json"
    markdown_path = repositories_dir / f"{result.spec.slug}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_repository_report(payload), encoding="utf-8")
    return json_path, markdown_path


def render_repository_report(payload: Mapping[str, object]) -> str:
    repository = payload.get("repository", {})
    if not isinstance(repository, Mapping):
        repository = {}
    analysis = payload.get("analysis")
    lines = [
        f"# Repository Validation: {repository.get('name', repository.get('slug', 'unknown'))}",
        "",
        f"Repository: {repository.get('url', 'N/A')}",
        f"Type: {repository.get('repository_type', 'N/A')}",
        f"Outcome: `{payload.get('outcome', 'unknown')}`",
        f"Resolved HEAD: `{payload.get('clone', {}).get('head_sha') if isinstance(payload.get('clone'), Mapping) else 'N/A'}`",
        f"Repeat determinism: `{_mapping_value(payload.get('determinism'), 'status', 'N/A')}`",
        "",
        "## Performance",
        "",
        _markdown_table(
            ("clone_ms", "collection_ms", "normalization_ms", "analyzer_ms", "score_engine_ms", "total_ms"),
            [
                [
                    _mapping_value(payload.get("timings_ms"), key, "N/A")
                    for key in (
                        "clone_ms",
                        "collection_ms",
                        "normalization_ms",
                        "analyzer_ms",
                        "score_engine_ms",
                        "total_ms",
                    )
                ]
            ],
        ),
        "",
        "Source timings:",
        "",
        f"`{json.dumps(_mapping_value(payload.get('timings_ms'), 'source_ms', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Capability snapshot",
        "",
        _capability_markdown(payload.get("capabilities")),
        "",
        "## Checkout inventory (validation-only observation)",
        "",
        _inventory_markdown(payload.get("inventory")),
        "",
    ]
    if not isinstance(analysis, Mapping):
        lines.extend(["## Analysis", "", "No production envelope was produced.", ""])
        errors = payload.get("errors")
        if errors:
            lines.append(f"Errors: `{json.dumps(errors, ensure_ascii=False)}`")
        return "\n".join(lines) + "\n"
    score = analysis.get("score")
    lines.extend(
        [
            "## Score Engine v1",
            "",
            _score_markdown(score),
            "",
            "## Category results",
            "",
            _category_summary_markdown(analysis.get("categories")),
            "",
        ]
    )
    for category in analysis.get("categories", ()):
        if isinstance(category, Mapping):
            lines.extend(_category_detail_markdown(category))
    lines.extend(
        [
            "## GitHub/SourceCraft boundary",
            "",
            "This run uses public Git checkout facts only. Security is SourceCraft AppSec-only; production Issues and CI/CD providers are exercised only by controlled SourceCraft runs. GitHub Issues, Actions, CodeQL, Dependabot, and other GitHub APIs were not substituted.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _analysis_payload(envelope: Any, capabilities: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    categories = [_category_payload(result, envelope.facts, capabilities) for result in envelope.category_results]
    return {
        "request": envelope.request.model_dump(mode="json"),
        "facts_digest": envelope.facts_digest,
        "facts": envelope.facts.model_dump(mode="json"),
        "source_statuses": [item.model_dump(mode="json") for item in envelope.facts.source_statuses],
        "limitations": [item.model_dump(mode="json") for item in envelope.facts.limitations],
        "status": envelope.status.model_dump(mode="json"),
        "score": envelope.score.model_dump(mode="json") if envelope.score is not None else None,
        "categories": categories,
        "policy_digest": envelope.policy_digest,
        "tool_versions": dict(envelope.tool_versions),
    }


def _category_payload(result: Any, facts: Any, capabilities: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    category = result.category.value
    source, capability_ids = CATEGORY_SOURCES[category]
    group = getattr(facts, {"code_health": "code_health"}.get(category, category), None)
    if category == "activity":
        group = facts.git
    observations = [item.model_dump(mode="json") for item in group.observations] if group else []
    relevant_capabilities = {item: capabilities.get(item, {}) for item in capability_ids}
    live_verified = bool(relevant_capabilities) and all(
        item.get("state") == "available" for item in relevant_capabilities.values()
    )
    return {
        "category": category,
        "analyzer_id": result.analyzer_id,
        "analyzer_version": result.analyzer_version,
        "policy_version": POLICY_VERSIONS[category],
        "source": source,
        "adapter_capabilities": relevant_capabilities,
        "live_verified": live_verified,
        "status": result.status.value,
        "score": result.score,
        "coverage": result.coverage.model_dump(mode="json"),
        "confidence": result.confidence.model_dump(mode="json"),
        "evidence_count": len(result.evidence),
        "finding_count": len(result.findings),
        "metrics": {item.name: item.value for item in result.metrics},
        "component_scores": {item.name: item.score for item in result.metrics if item.score is not None},
        "normalized_observations": observations,
        "facts_available": bool(group and group.available),
        "facts_limitations": [item.model_dump(mode="json") for item in group.limitations] if group else [],
        "limitations": [item.model_dump(mode="json") for item in result.limitations],
        "findings": [item.model_dump(mode="json") for item in result.findings],
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "source_versions": dict(result.source_versions),
        "score_signals": dict(result.score_signals),
        "formula_substitution": _formula_substitution(category, result),
    }


def _formula_substitution(category: str, result: Any) -> str:
    metrics = {item.name: item.value for item in result.metrics}
    score = result.score
    if score is None:
        return "not computable from available facts; score remains null"
    if category == "documentation":
        return (
            "documentation_score = 0.40*completeness + 0.20*instructions + "
            f"0.25*vale_quality + 0.15*readability = {score:.2f}; "
            f"components={_compact_metrics(metrics, ('completeness', 'instructions', 'vale_quality', 'readability'))}"
        )
    if category == "activity":
        return (
            "activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + "
            f"0.15*breadth)*(0.25 + 0.75*integrity) = {score:.2f}; "
            f"components={_compact_metrics(metrics, ('history', 'cadence', 'recency', 'breadth', 'integrity'))}"
        )
    if category == "code_health":
        weights = (
            ("maintainability_debt", 0.35),
            ("complexity", 0.15),
            ("duplication", 0.15),
            ("hotspots_churn", 0.15),
            ("todo_debt", 0.10),
            ("git_structure", 0.10),
        )
        active = [
            (name, weight, metrics[name]) for name, weight in weights if isinstance(metrics.get(name), (int, float))
        ]
        expression = " + ".join(f"{value:.2f}*{weight:.2f}" for _name, weight, value in active)
        denominator = sum(weight for _name, weight, _value in active)
        return f"code_health_score = ({expression}) / {denominator:.2f} = {score:.2f} (active components only)"
    return f"{category} policy returned score={score:.2f}; see normalized metrics and policy version"


def _score_markdown(score: object) -> str:
    if not isinstance(score, Mapping):
        return "No numeric Repo Health Score v1 was produced (`INSUFFICIENT_DATA`)."
    breakdown = score.get("breakdown") if isinstance(score.get("breakdown"), Mapping) else {}
    return "\n".join(
        [
            f"- Overall score: **{_fmt(score.get('overall_score'))}**",
            f"- Presentation state: `{score.get('presentation_state', 'N/A')}`",
            f"- Score status: `{score.get('score_status', 'N/A')}`",
            f"- Score before caps: `{_fmt(score.get('score_before_caps'))}`",
            f"- Coverage K: `{_fmt_ratio(score.get('coverage_k'))}`; confidence: `{_fmt_ratio(score.get('confidence'))}`; evidence coverage: `{_fmt_ratio(score.get('evidence_coverage'))}`",
            f"- Applied caps: `{json.dumps(score.get('applied_caps', []), ensure_ascii=False)}`",
            f"- Category contribution records: `{len(breakdown.get('contributions', [])) if isinstance(breakdown, Mapping) else 0}`",
        ]
    )


def _category_summary_markdown(categories: object) -> str:
    rows = []
    for item in categories if isinstance(categories, (list, tuple)) else ():
        if isinstance(item, Mapping):
            rows.append(
                [
                    item.get("category"),
                    item.get("status"),
                    _fmt(item.get("score")),
                    _mapping_value(item.get("coverage"), "status", "N/A"),
                    _mapping_value(item.get("confidence"), "level", "N/A"),
                    item.get("evidence_count", 0),
                    "YES" if item.get("live_verified") else "NO",
                ]
            )
    return _markdown_table(("category", "status", "score", "coverage", "confidence", "evidence", "live verified"), rows)


def _category_detail_markdown(category: Mapping[str, object]) -> list[str]:
    name = str(category.get("category", "unknown"))
    observations = category.get("normalized_observations", [])
    metrics = category.get("metrics", {})
    limitations = category.get("limitations", [])
    lines = [
        f"### {name}",
        "",
        f"Source/adapter: **{category.get('source', 'N/A')}**",
        f"Status: `{category.get('status', 'N/A')}`; score: **{_fmt(category.get('score'))}**; coverage: `{_mapping_value(category.get('coverage'), 'status', 'N/A')}`; confidence: `{_mapping_value(category.get('confidence'), 'level', 'N/A')}`",
        f"Evidence: `{category.get('evidence_count', 0)}`; findings: `{category.get('finding_count', 0)}`; live verified: `{category.get('live_verified', False)}`",
        f"Policy/analyzer: `{category.get('policy_version', 'N/A')}` / `{category.get('analyzer_version', 'N/A')}`",
        "",
        f"Formula substitution: `{category.get('formula_substitution', 'N/A')}`",
        "",
        "Normalized observations:",
        "",
        "```json",
        json.dumps(observations, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "Metrics/components:",
        "",
        "```json",
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        f"Limitations: `{json.dumps(limitations, ensure_ascii=False)}`",
        "",
    ]
    return lines


def _capability_markdown(capabilities: object) -> str:
    rows = []
    if isinstance(capabilities, Mapping):
        for name, value in sorted(capabilities.items()):
            if isinstance(value, Mapping):
                rows.append([name, value.get("state"), value.get("configured"), value.get("reason")])
    return _markdown_table(("engine", "state", "configured", "reason"), rows)


def _inventory_markdown(inventory: object) -> str:
    if not isinstance(inventory, Mapping):
        return "No checkout inventory available."
    rows = [
        [key, value]
        for key, value in inventory.items()
        if key not in {"name_sample", "source_name_sample", "artifact_paths"}
    ]
    text = _markdown_table(("observation", "value"), rows)
    artifacts = inventory.get("artifact_paths", [])
    if artifacts:
        text += "\n\nPotential artifact paths (observation only):\n\n" + "\n".join(f"- `{item}`" for item in artifacts)
    return text


def _markdown_table(headers: tuple[str, ...], rows: list[list[object]]) -> str:
    if not rows:
        rows = [["N/A" for _ in headers]]
    header = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_md_cell(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _mapping_value(value: object, key: str, default: object) -> object:
    return value.get(key, default) if isinstance(value, Mapping) else default


def _compact_metrics(metrics: Mapping[str, object], names: tuple[str, ...]) -> str:
    return ", ".join(f"{name}={_fmt(metrics.get(name))}" for name in names)


def _fmt(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _fmt_ratio(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _tracked_paths(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return [item.decode("utf-8", errors="replace") for item in completed.stdout.split(b"\x00") if item]


def _redact_process_text(value: str) -> str:
    return _SECRET_VALUE.sub(lambda match: f"{match.group(1)}[REDACTED]", value)


class _suppress_os_error:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> bool:
        return exc_type is OSError


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _configure_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level)
    # PyDriller logs one line per commit at INFO. Keep the validation output
    # readable while retaining the structured production-run events.
    logging.getLogger("pydriller").setLevel(logging.WARNING)
    logging.getLogger("git").setLevel(logging.WARNING)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def _parse_as_of(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must include an explicit timezone")
    return parsed.astimezone(UTC)


def default_checkout_root(label: str) -> Path:
    """Use a short OS temp path on Windows so large Git trees can checkout."""

    if os.name == "nt":
        return Path(tempfile.gettempdir()) / "repo-health-validation" / label
    return Path(".sources/validation") / label


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Public GitHub repository URL")
    parser.add_argument("--slug", required=True, help="Stable artifact slug")
    parser.add_argument("--name", default=None)
    parser.add_argument("--type", default="MANUAL", dest="repository_type")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/validation/manual"))
    parser.add_argument("--checkout-root", type=Path, default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--clone-timeout", type=float, default=600.0)
    parser.add_argument("--analysis-timeout", type=float, default=900.0)
    parser.add_argument("--enable-sonarqube", action="store_true")
    parser.add_argument("--sonar-url", default=None)
    args = parser.parse_args(argv)
    try:
        spec = RepositorySpec(
            slug=args.slug,
            name=args.name or args.slug,
            url=args.url,
            repository_type=args.repository_type,
            hypothesis="manual single-repository validation",
        )
        validate_manifest(REPOSITORY_MANIFEST)
        as_of = _parse_as_of(args.as_of)
        clone = clone_repository(
            spec,
            args.checkout_root or default_checkout_root("manual"),
            timeout_seconds=args.clone_timeout,
        )
        result = validate_checkout(
            spec,
            clone,
            as_of=as_of,
            analysis_timeout_seconds=args.analysis_timeout,
            enable_sonarqube=args.enable_sonarqube,
            sonar_url=args.sonar_url,
            sonar_token=os.getenv("SONAR_TOKEN"),
        )
        json_path, markdown_path = write_result(result, args.output_dir)
        print(
            json.dumps(
                {"result": result.public_dict(), "json": str(json_path), "markdown": str(markdown_path)},
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


__all__ = [
    "CATEGORY_SOURCES",
    "REPOSITORY_MANIFEST",
    "SOURCECRAFT_ONLY_CATEGORIES",
    "CloneResult",
    "RepositorySpec",
    "TimingBreakdown",
    "ValidationRunResult",
    "clone_repository",
    "collect_inventory",
    "default_checkout_root",
    "render_repository_report",
    "validate_checkout",
    "validate_manifest",
    "write_result",
]
