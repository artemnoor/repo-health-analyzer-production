"""Vale-backed documentation quality adapter.

Vale owns prose parsing and rule execution.  This module owns only the
repository-health boundary: deterministic file selection, bounded process
invocation, raw JSON validation, normalized facts, and mapping into the
neutral analyzer contracts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import structlog

from ....analysis.analyzer_integration.ports import ProcessExecutor
from ..calibration_policy_v2 import (
    DOCUMENTATION_FINDING_DENSITY_SCALE,
    DOCUMENTATION_FINDING_MIN_WORDS,
    DOCUMENTATION_FINDING_PENALTY,
    DOCUMENTATION_POLICY_REVISION,
    documentation_score,
)
from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    FindingLocation,
    Limitation,
    MetricValue,
)
from .process import ProcessOutput, ProcessRequest, SubprocessProcess, workspace_root

log = structlog.get_logger("vale.adapter")

VALE_ANALYZER_ID = "vale.documentation"
VALE_SOURCE_COMMIT = "ba6a2c6a725295eb6b7698336d22dec8ffc4af1c"
VALE_VALIDATED_VERSION = "3.22.0"
VALE_POLICY_REVISION = "vale-3.22.0-policy-v2"
VALE_CONFIG_RELATIVE = Path("config/analyzers/vale.yaml")
VALE_INI_RELATIVE = Path("config/analyzers/vale/.vale.ini")
VALE_STYLES_RELATIVE = Path("config/analyzers/vale/styles")
_DEFAULT_EXTENSIONS = (".md", ".mdx", ".markdown", ".rst", ".txt")
_DEFAULT_EXCLUDED_DIRECTORIES = (
    ".git",
    ".hg",
    ".svn",
    "vendor",
    "node_modules",
    "build",
    "dist",
    "cache",
    ".cache",
    "generated",
)
_DEFAULT_EXTENSIONLESS_NAMES = (
    "README",
    "CONTRIBUTING",
    "CHANGELOG",
    "ARCHITECTURE",
    "DESIGN",
    "DECISIONS",
)
_SEVERITY_WEIGHTS = {
    "suggestion": 0.25,
    "warning": 1.0,
    "error": 2.0,
    "fatal": 3.0,
}
_GENERIC_SEVERITIES = {
    "suggestion": "low",
    "warning": "medium",
    "error": "high",
    "fatal": "critical",
}


def _policy_files(root: Path) -> tuple[Path, ...]:
    return (
        root / VALE_CONFIG_RELATIVE,
        root / VALE_INI_RELATIVE,
        *(
            sorted((root / VALE_STYLES_RELATIVE).glob("**/*.yml"))
            if (root / VALE_STYLES_RELATIVE).is_dir()
            else ()
        ),
        *(
            sorted((root / VALE_STYLES_RELATIVE).glob("**/*.yaml"))
            if (root / VALE_STYLES_RELATIVE).is_dir()
            else ()
        ),
    )


def _policy_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _policy_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def _definition_version() -> str:
    """Include the checked-in policy digest in the analyzer cache identity."""
    try:
        return f"{VALE_POLICY_REVISION}-{_policy_digest(workspace_root())[:12]}"
    except (OSError, ValueError):
        return VALE_POLICY_REVISION


VALE_DEFINITION = AnalyzerDefinition(
    id=VALE_ANALYZER_ID,
    version=_definition_version(),
    category="documentation-quality",
    dimensions=("docs",),
    requires=("local_scan",),
    phase=25,
    cost=30,
    timeout=120,
    cache_policy="read_write",
    source_commit=VALE_SOURCE_COMMIT,
    enabled_by_mode=("backfill", "diff", "fast", "full", "offline"),
)


@dataclass(frozen=True)
class ValePolicy:
    """Validated paths and settings loaded from the versioned policy files."""

    root: Path
    policy_file: Path
    config_file: Path
    styles_dir: Path
    data: Mapping[str, Any]
    digest: str

    @property
    def policy(self) -> Mapping[str, Any]:
        value = self.data.get("policy")
        return value if isinstance(value, Mapping) else {}

    @property
    def analyzer(self) -> Mapping[str, Any]:
        value = self.data.get("analyzer")
        return value if isinstance(value, Mapping) else {}

    @property
    def revision(self) -> str:
        return str(self.policy.get("policy_revision") or VALE_POLICY_REVISION)

    @property
    def tool_version(self) -> str:
        return str(self.policy.get("validated_vale_version") or VALE_VALIDATED_VERSION)

    @property
    def timeout_seconds(self) -> float:
        return max(0.1, float(self.policy.get("timeout_seconds") or 90.0))

    @property
    def output_cap_bytes(self) -> int:
        return max(1024, int(self.policy.get("output_cap_bytes") or 16 * 1024 * 1024))

    @property
    def max_files_per_batch(self) -> int:
        return max(1, int(self.policy.get("max_files_per_batch") or 128))

    @property
    def max_command_bytes(self) -> int:
        return max(1024, int(self.policy.get("max_command_bytes") or 200_000))

    @property
    def extensions(self) -> tuple[str, ...]:
        raw = self.policy.get("supported_extensions") or _DEFAULT_EXTENSIONS
        return tuple(sorted({str(value).casefold() for value in raw if str(value).strip()}))

    @property
    def extensionless_names(self) -> tuple[str, ...]:
        raw = self.policy.get("extensionless_names") or _DEFAULT_EXTENSIONLESS_NAMES
        return tuple(sorted({str(value).casefold() for value in raw if str(value).strip()}))

    @property
    def excluded_directories(self) -> frozenset[str]:
        raw = self.policy.get("excluded_directories") or _DEFAULT_EXCLUDED_DIRECTORIES
        return frozenset(str(value).casefold() for value in raw)

    @property
    def severity_weights(self) -> Mapping[str, float]:
        raw = self.policy.get("severity_weights")
        if not isinstance(raw, Mapping):
            return _SEVERITY_WEIGHTS
        return {
            str(key).casefold(): max(0.0, float(value))
            for key, value in raw.items()
            if str(key).strip()
        }

    @property
    def minimum_words_per_file(self) -> int:
        score = self.policy.get("score")
        value = score.get("minimum_words_per_file") if isinstance(score, Mapping) else None
        return max(1, int(value or 20))

    @property
    def density_scale(self) -> float:
        score = self.policy.get("score")
        value = score.get("density_scale") if isinstance(score, Mapping) else None
        return max(0.0, float(value or 40.0))

    @property
    def max_penalty(self) -> float:
        score = self.policy.get("score")
        value = score.get("max_penalty") if isinstance(score, Mapping) else None
        return max(0.0, min(100.0, float(value if value is not None else 30.0)))


@dataclass(frozen=True)
class ValeFindingFact:
    """Normalized finding retained inside the Vale adapter boundary."""

    file: str
    rule: str
    severity: str
    message: str
    line: int | None
    match: str | None = None
    span: tuple[int, int] | None = None
    json_pointer: str | None = None
    finding_id: str = ""


@dataclass(frozen=True)
class ValeFacts:
    """Adapter-owned normalized Vale observations."""

    files: tuple[str, ...]
    findings: tuple[ValeFindingFact, ...]
    metrics: Mapping[str, float]
    execution_status: str
    failure_kind: str | None
    coverage: float
    metrics_coverage: float
    duration_ms: int
    policy_revision: str
    policy_digest: str
    tool_version: str
    failed_batches: tuple[Mapping[str, Any], ...] = ()
    threshold_exit_count: int = 0
    threshold_exit_codes: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExecutableResolution:
    path: Path | None
    source: str
    candidate_count: int


class ValePayloadError(ValueError):
    """Raised when Vale returns a structurally invalid JSON payload."""


def load_vale_policy(root: Path | None = None) -> ValePolicy:
    """Load and validate the repository-owned Vale policy."""
    import yaml

    resolved_root = Path(root or workspace_root()).resolve()
    policy_file = resolved_root / VALE_CONFIG_RELATIVE
    config_file = resolved_root / VALE_INI_RELATIVE
    styles_dir = resolved_root / VALE_STYLES_RELATIVE
    raw = yaml.safe_load(policy_file.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValePayloadError("Vale policy must be a YAML mapping")
    if not config_file.is_file() or not styles_dir.is_dir():
        raise FileNotFoundError("Vale config or styles directory is missing")
    analyzer = raw.get("analyzer")
    policy = raw.get("policy")
    if not isinstance(analyzer, Mapping) or not isinstance(policy, Mapping):
        raise ValePayloadError("Vale policy requires analyzer and policy mappings")
    if str(analyzer.get("id")) != VALE_ANALYZER_ID:
        raise ValePayloadError("Vale policy analyzer id does not match the adapter")
    if str(policy.get("policy_revision") or "") != VALE_POLICY_REVISION:
        raise ValePayloadError("Vale policy revision does not match the adapter")
    return ValePolicy(
        root=resolved_root,
        policy_file=policy_file,
        config_file=config_file,
        styles_dir=styles_dir,
        data=raw,
        digest=_policy_digest(resolved_root),
    )


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_positive_int(value: object) -> int | None:
    number = _as_number(value)
    if number is None or number <= 0:
        return None
    return int(number)


def _pointer_part(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _relative_path(root: Path, value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValePayloadError("Vale finding has an empty path")
    root_resolved = root.resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    try:
        relative = candidate.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise ValePayloadError("Vale finding path escapes repository root") from exc
    return relative.as_posix()


def _finding_id(
    file: str,
    rule: str,
    severity: str,
    line: int | None,
    span: tuple[int, int] | None,
    message: str,
    match: str | None,
) -> str:
    payload = json.dumps(
        [file, rule, severity, line, span, message, match],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"{VALE_ANALYZER_ID}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def parse_diagnostics(payload: object, repository_root: Path) -> tuple[ValeFindingFact, ...]:
    """Parse Vale's path-to-array JSON report into stable normalized facts."""
    if not isinstance(payload, Mapping):
        raise ValePayloadError("Vale diagnostics must be a path-to-array mapping")
    facts: list[ValeFindingFact] = []
    for raw_path, raw_items in payload.items():
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
            raise ValePayloadError("Vale diagnostics entry must be an array")
        file = _relative_path(repository_root, raw_path)
        for index, item in enumerate(raw_items):
            if not isinstance(item, Mapping):
                raise ValePayloadError("Vale diagnostic must be an object")
            raw_severity = str(
                item.get("Severity") or item.get("severity") or "suggestion"
            ).casefold()
            severity = raw_severity if raw_severity in _GENERIC_SEVERITIES else "suggestion"
            rule = str(
                item.get("Check")
                or item.get("check")
                or item.get("Rule")
                or item.get("rule")
                or "vale.unknown"
            )
            message = str(
                item.get("Message")
                or item.get("message")
                or item.get("Description")
                or item.get("description")
                or "Vale finding"
            )
            line = _as_positive_int(item.get("Line") if "Line" in item else item.get("line"))
            raw_span = item.get("Span") if "Span" in item else item.get("span")
            span: tuple[int, int] | None = None
            if (
                isinstance(raw_span, Sequence)
                and not isinstance(raw_span, (str, bytes, bytearray))
                and len(raw_span) >= 2
            ):
                start = _as_positive_int(raw_span[0])
                end = _as_positive_int(raw_span[1])
                if start is not None and end is not None and end >= start:
                    span = (start, end)
            raw_match = item.get("Match") if "Match" in item else item.get("match")
            match = str(raw_match) if isinstance(raw_match, str) else None
            pointer = f"/{_pointer_part(raw_path)}/{index}"
            facts.append(
                ValeFindingFact(
                    file=file,
                    rule=rule,
                    severity=severity,
                    message=message,
                    line=line,
                    match=match,
                    span=span,
                    json_pointer=pointer,
                    finding_id=_finding_id(file, rule, severity, line, span, message, match),
                )
            )
    return tuple(facts)


def parse_metrics(payload: object) -> dict[str, float]:
    """Parse flat or per-file Vale metrics, aggregating numeric values."""
    if not isinstance(payload, Mapping):
        raise ValePayloadError("Vale metrics must be a JSON mapping")
    metrics: dict[str, float] = {}
    for key, value in payload.items():
        number = _as_number(value)
        if number is not None:
            metrics[str(key)] = metrics.get(str(key), 0.0) + number
            continue
        if not isinstance(value, Mapping):
            if value is not None:
                raise ValePayloadError("Vale metrics values must be numeric or mappings")
            continue
        for nested_key, nested_value in value.items():
            nested_number = _as_number(nested_value)
            if nested_number is not None:
                name = str(nested_key)
                metrics[name] = metrics.get(name, 0.0) + nested_number
    return metrics


def _inventory_paths(inventory: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    for key in ("documentation_files", "doc_files", "files", "paths"):
        if key not in inventory:
            continue
        raw = inventory.get(key)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            return True, ()
        values: list[str] = []
        for item in raw:
            if isinstance(item, Mapping):
                item = item.get("path") or item.get("file") or item.get("file_path")
            if item:
                values.append(str(item))
        return True, tuple(values)
    return False, ()


def _is_binary(path: Path) -> bool:
    try:
        return b"\0" in path.read_bytes()[:4096]
    except OSError:
        return True


def _is_supported(relative: Path, policy: ValePolicy) -> bool:
    suffix = relative.suffix.casefold()
    if suffix:
        return suffix in policy.extensions
    return relative.name.casefold() in policy.extensionless_names


def discover_documentation_files(
    repository_root: Path,
    policy: ValePolicy,
    inventory: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return sorted, repository-relative prose files within the checkout."""
    root = repository_root.resolve()
    supplied, supplied_paths = _inventory_paths(inventory or {})
    candidates: list[Path] = []
    if supplied:
        for raw in supplied_paths:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = root / candidate
            candidates.append(candidate)
    elif root.is_dir():
        candidates.extend(path for path in root.rglob("*") if path.is_file())

    selected: set[str] = set()
    for candidate in candidates:
        try:
            relative = candidate.resolve().relative_to(root)
        except ValueError:
            continue
        if any(part.casefold() in policy.excluded_directories for part in relative.parts[:-1]):
            continue
        if not candidate.is_file() or not _is_supported(relative, policy) or _is_binary(candidate):
            continue
        selected.add(relative.as_posix())
    result = tuple(sorted(selected))
    log.info(
        "vale_discovery_completed",
        phase="discover",
        status="completed",
        repository_file_count=len(result),
        inventory_used=supplied,
        excluded_directory_count=len(policy.excluded_directories),
    )
    return result


def batch_documentation_files(
    files: Sequence[str],
    *,
    config_path: Path,
    max_files: int,
    max_command_bytes: int,
) -> tuple[tuple[str, ...], ...]:
    """Split paths deterministically without exceeding configured argv bounds."""
    batches: list[tuple[str, ...]] = []
    current: list[str] = []
    base_size = len(str(config_path).encode("utf-8")) + 32
    current_size = base_size
    for file in sorted({str(path) for path in files}):
        addition = len(file.encode("utf-8")) + 3
        if current and (len(current) >= max_files or current_size + addition > max_command_bytes):
            batches.append(tuple(current))
            current = []
            current_size = base_size
        current.append(file)
        current_size += addition
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def resolve_vale_executable(context: AnalyzerContext, policy: ValePolicy) -> ExecutableResolution:
    """Resolve explicit overrides, repository candidates, then PATH."""
    root = policy.root
    candidates: list[tuple[str, str]] = []
    for key in (VALE_ANALYZER_ID, "vale", "vale.exe"):
        value = context.tool_paths.get(key)
        if value:
            candidates.append((f"tool_path:{key}", str(value)))
    configured = policy.policy.get("executable")
    configured_candidates = (
        configured.get("configured_candidates") if isinstance(configured, Mapping) else None
    )
    if not isinstance(configured_candidates, Sequence) or isinstance(
        configured_candidates, (str, bytes, bytearray)
    ):
        configured_candidates = ("bin/vale.exe", "bin/vale")
    candidates.extend(
        ("configured_candidate", str(value)) for value in configured_candidates if value
    )
    if not candidates or bool(
        configured.get("allow_path_lookup", True) if isinstance(configured, Mapping) else True
    ):
        candidates.extend(("path_lookup", name) for name in ("vale.exe", "vale"))

    seen: set[str] = set()
    for source, raw in candidates:
        if raw in seen:
            continue
        seen.add(raw)
        candidate = Path(raw)
        if not candidate.is_absolute():
            project_candidate = root / candidate
            if project_candidate.is_file():
                return ExecutableResolution(project_candidate.resolve(), source, len(candidates))
            resolved = shutil.which(raw)
            if resolved:
                return ExecutableResolution(Path(resolved).resolve(), source, len(candidates))
        elif candidate.is_file():
            return ExecutableResolution(candidate.resolve(), source, len(candidates))
    return ExecutableResolution(None, "missing", len(candidates))


def _raw_ref(raw_values: Sequence[str]) -> str:
    digest = hashlib.sha256("\n".join(raw_values).encode("utf-8", errors="replace")).hexdigest()
    return f"vale://{VALE_ANALYZER_ID}/{digest}"


def _safe_kind(
    kind: str,
) -> Literal["missing_capability", "insufficient_denominator", "timeout", "error", "other"]:
    if kind in {"missing_capability", "insufficient_denominator", "timeout", "error", "other"}:
        return cast(
            Literal["missing_capability", "insufficient_denominator", "timeout", "error", "other"],
            kind,
        )
    return "error"


def _evidence(
    context: AnalyzerContext,
    policy: ValePolicy,
    *,
    path: str | None = None,
    line: int | None = None,
    pointer: str | None = None,
    snippet: str | None = None,
    confidence: float = 1.0,
) -> EvidenceRef:
    snippet_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest() if snippet else None
    return EvidenceRef(
        source=VALE_ANALYZER_ID,
        source_commit=VALE_SOURCE_COMMIT,
        tool_version=policy.tool_version,
        path=path,
        line_start=line,
        line_end=line,
        json_pointer=pointer,
        snippet_hash=snippet_hash,
        collected_at=context.as_of_ts,
        confidence=max(0.0, min(1.0, confidence)),
        redaction="partial" if snippet else "none",
    )


def _source_versions(policy: ValePolicy) -> dict[str, str]:
    return {
        "vale": policy.tool_version,
        "vale_policy": policy.revision,
        "vale_policy_digest": policy.digest,
        "vale_source_commit": VALE_SOURCE_COMMIT,
    }


def _failure_result(
    definition: AnalyzerDefinition,
    policy: ValePolicy,
    *,
    reason: str,
    kind: str,
    diagnostics: Mapping[str, Any],
    raw_ref: str | None = None,
    status: AnalyzerStatus = AnalyzerStatus.ERROR,
) -> AnalyzerResult:
    normalized_diagnostics = dict(diagnostics)
    normalized_diagnostics.setdefault("coverage", 0.0)
    normalized_diagnostics.setdefault("metrics_coverage", 0.0)
    normalized_diagnostics.setdefault("confidence", 0.0)
    return AnalyzerResult(
        analyzer_id=definition.id,
        analyzer_version=definition.version,
        status=status,
        limitations=(Limitation(reason=reason, kind=_safe_kind(kind)),),
        total_weight=1,
        raw_payload_ref=raw_ref,
        source_versions=_source_versions(policy),
        diagnostics=normalized_diagnostics,
    )


def _process_failure(output: ProcessOutput) -> tuple[str, str]:
    if output.timed_out:
        return "timeout", "Vale process timed out"
    if output.truncated:
        return "error", "Vale output was truncated"
    if output.start_error is not None:
        return "error", "Vale process failed to start"
    return "error", "Vale process failed"


def _metric(
    name: str,
    value: float | int,
    *,
    population: int | None = None,
    denominator: int | None = None,
    evidence: Sequence[EvidenceRef] = (),
) -> MetricValue:
    return MetricValue(
        name=name,
        dimension="docs",
        value=value,
        population=population,
        denominator=denominator,
        evidence_refs=tuple(evidence),
    )


def _documentation_inventory_components(
    repository_root: Path,
    discovered_files: Sequence[str],
    excluded_directories: Sequence[str],
) -> tuple[float, float, dict[str, bool]]:
    """Compute calibration-v2 completeness and executable-instruction inputs.

    The scan is deliberately bounded to the same excluded directory policy as
    Vale.  It returns only booleans/ratios; document text never leaves this
    function and is not retained in diagnostics.
    """
    excluded = {str(item).casefold() for item in excluded_directories}
    files: set[str] = set()
    for item in repository_root.rglob("*"):
        if not item.is_file():
            continue
        try:
            relative = item.relative_to(repository_root)
        except ValueError:
            continue
        if any(part.casefold() in excluded for part in relative.parts[:-1]):
            continue
        files.add(relative.as_posix().casefold())

    readme = any(item == "readme.md" or item.startswith("readme.") for item in files)
    license_file = any(item.startswith("license") for item in files)
    contributing = any(item.startswith("contributing") for item in files)
    codeowners = any(item == "codeowners" or item.endswith("/codeowners") for item in files)

    text_parts: list[str] = []
    for relative in sorted(set(discovered_files)):
        path = repository_root / relative
        try:
            if path.stat().st_size > 2_000_000:
                continue
            if path.suffix.casefold() in {".md", ".mdx", ".markdown", ".rst", ".txt"}:
                text_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    import re

    instructions = bool(
        re.search(
            r"\b(install|setup|run|build|test|usage|quickstart)\b",
            "\n".join(text_parts),
            flags=re.IGNORECASE,
        )
    )
    completeness = 100.0 * sum((readme, license_file, contributing, codeowners)) / 4.0
    return completeness, 100.0 if instructions else 0.0, {
        "readme": readme,
        "license": license_file,
        "contributing": contributing,
        "codeowners": codeowners,
        "instructions": instructions,
    }


def _build_result(
    context: AnalyzerContext,
    policy: ValePolicy,
    *,
    definition: AnalyzerDefinition,
    discovered_files: tuple[str, ...],
    analyzed_files: tuple[str, ...],
    findings: tuple[ValeFindingFact, ...],
    metrics: Mapping[str, float],
    failed_batches: tuple[Mapping[str, Any], ...],
    metrics_batches: int,
    metrics_targets: int,
    total_batches: int,
    successful_batches: int,
    duration_ms: int,
    raw_values: Sequence[str],
    executable_source: str,
    threshold_exit_codes: Sequence[int] = (),
) -> AnalyzerResult:
    execution_status = "partial" if failed_batches else "completed"
    failure_kind = str(failed_batches[0].get("kind") or "error") if failed_batches else None
    normalized_threshold_codes = tuple(threshold_exit_codes)
    facts = ValeFacts(
        files=analyzed_files,
        findings=findings,
        metrics=dict(metrics),
        execution_status=execution_status,
        failure_kind=failure_kind,
        coverage=len(analyzed_files) / len(discovered_files) if discovered_files else 0.0,
        metrics_coverage=metrics_batches / max(1, metrics_targets),
        duration_ms=duration_ms,
        policy_revision=policy.revision,
        policy_digest=policy.digest,
        tool_version=policy.tool_version,
        failed_batches=failed_batches,
        threshold_exit_count=len(normalized_threshold_codes),
        threshold_exit_codes=normalized_threshold_codes,
    )
    file_count = len(facts.files)
    coverage = facts.coverage
    metrics_coverage = facts.metrics_coverage
    confidence = min(coverage, metrics_coverage)
    words = max(0.0, facts.metrics.get("words", 0.0))
    denominator = max(words, float(file_count * policy.minimum_words_per_file))
    weighted_points = sum(
        policy.severity_weights.get(item.severity, 0.0) for item in facts.findings
    )
    density = weighted_points / denominator if denominator > 0 else 0.0
    penalty = min(
        100.0,
        weighted_points * DOCUMENTATION_FINDING_PENALTY
        + weighted_points / max(words, DOCUMENTATION_FINDING_MIN_WORDS) * DOCUMENTATION_FINDING_DENSITY_SCALE,
    )
    quality_score = max(0.0, min(100.0, 100.0 - penalty))
    completeness, instructions, presence = _documentation_inventory_components(
        context.repo_path,
        discovered_files,
        tuple(policy.excluded_directories),
    )
    complex_words = max(0.0, facts.metrics.get("complex_words", 0.0))
    long_words = max(0.0, facts.metrics.get("long_words", 0.0))
    readability = max(
        0.0,
        100.0
        - 100.0 * (complex_words / max(words, 1.0))
        - 60.0 * (long_words / max(words, 1.0)),
    )
    final_score = documentation_score(
        completeness=completeness,
        instructions=instructions,
        vale_quality=quality_score,
        readability=readability,
    )

    evidence: list[EvidenceRef] = []
    generic_findings: list[Finding] = []
    counts: Counter[str] = Counter()
    for item in facts.findings:
        counts[item.severity] += 1
        ref = _evidence(
            context,
            policy,
            path=item.file,
            line=item.line,
            pointer=item.json_pointer,
            snippet=item.match,
            confidence=confidence,
        )
        evidence.append(ref)
        generic_findings.append(
            Finding(
                id=item.finding_id,
                analyzer_id=definition.id,
                subject=item.rule,
                dimension="docs",
                severity=cast(Any, _GENERIC_SEVERITIES[item.severity]),
                confidence=max(0.0, min(1.0, confidence)),
                reason=item.message,
                evidence_refs=(ref,),
                location=FindingLocation(path=item.file, line_start=item.line, line_end=item.line),
                remediation="Review the referenced documentation wording against the Repo Health Vale rule.",
                raw_impact=policy.severity_weights.get(item.severity, 0.0),
                applied_impact=policy.severity_weights.get(item.severity, 0.0),
            )
        )

    summary_ref = _evidence(context, policy, confidence=confidence)
    evidence.append(summary_ref)
    metrics_rows = [
        MetricValue(
            name="vale_quality",
            dimension="docs",
            value=quality_score,
            score=None,
            population=file_count,
            denominator=1,
            evidence_refs=(summary_ref,),
        ),
        MetricValue(
            name="documentation_score",
            dimension="docs",
            value=final_score,
            score=final_score,
            population=1,
            denominator=1,
            evidence_refs=(summary_ref,),
        ),
        _metric("documentation:completeness", completeness, evidence=(summary_ref,)),
        _metric("documentation:instructions", instructions, evidence=(summary_ref,)),
        _metric("documentation:readability", readability, evidence=(summary_ref,)),
        _metric(
            "vale_files_discovered",
            len(discovered_files),
            population=len(discovered_files),
            evidence=(summary_ref,),
        ),
        _metric("vale_files_analyzed", file_count, population=file_count, evidence=(summary_ref,)),
        _metric(
            "vale_findings",
            len(facts.findings),
            population=len(facts.findings),
            evidence=tuple(evidence[:1]),
        ),
        _metric(
            "vale_weighted_finding_points",
            weighted_points,
            population=len(facts.findings),
            evidence=(summary_ref,),
        ),
        _metric(
            "vale_finding_density",
            density,
            population=len(facts.findings),
            denominator=int(denominator) if denominator > 0 else None,
            evidence=(summary_ref,),
        ),
        _metric(
            "vale_coverage",
            coverage,
            population=len(analyzed_files),
            denominator=len(discovered_files) or None,
            evidence=(summary_ref,),
        ),
        _metric(
            "vale_metrics_coverage",
            metrics_coverage,
            population=metrics_batches,
            denominator=metrics_targets or None,
            evidence=(summary_ref,),
        ),
    ]
    for name, value in sorted(facts.metrics.items()):
        metrics_rows.append(_metric(f"vale:{name}", value, evidence=(summary_ref,)))

    has_content_error = any(item.severity in {"error", "fatal"} for item in facts.findings)
    status = (
        AnalyzerStatus.FAIL
        if has_content_error
        else AnalyzerStatus.WARN
        if facts.findings
        else AnalyzerStatus.PASS
    )
    limitations: list[Limitation] = []
    if facts.failed_batches:
        first_kind = str(facts.failed_batches[0].get("kind") or "error")
        limitations.append(
            Limitation(
                reason="One or more Vale batches did not complete; score covers only analyzed batches.",
                kind=_safe_kind(first_kind),
                affected_scope="documentation",
                evidence_refs=(summary_ref,),
            )
        )
        if status is AnalyzerStatus.PASS:
            status = AnalyzerStatus.WARN
    if coverage <= 0 or denominator <= 0:
        return AnalyzerResult(
            analyzer_id=definition.id,
            analyzer_version=definition.version,
            status=AnalyzerStatus.INCONCLUSIVE,
            metrics=tuple(metrics_rows),
            findings=tuple(generic_findings),
            evidence=tuple(evidence),
            limitations=(
                Limitation(
                    reason="Vale has no usable documentation denominator",
                    kind="insufficient_denominator",
                ),
            ),
            duration_ms=duration_ms,
            source_versions=_source_versions(policy),
            total_weight=1,
            raw_payload_ref=_raw_ref(raw_values),
            diagnostics={
                "execution_status": "inconclusive",
                "failure_kind": "insufficient_denominator",
                "discovered_files": len(discovered_files),
                "analyzed_files": file_count,
                "coverage": coverage,
                "metrics_coverage": metrics_coverage,
                "confidence": confidence,
                "executable_source": executable_source,
            },
        )

    diagnostics = {
        "execution_status": facts.execution_status,
        "discovered_files": len(discovered_files),
        "analyzed_files": file_count,
        "coverage": coverage,
        "metrics_coverage": metrics_coverage,
        "confidence": confidence,
        "batch_count": total_batches,
        "successful_batch_count": successful_batches,
        "metrics_target_count": metrics_targets,
        "failed_batches": [dict(item) for item in facts.failed_batches],
        "finding_counts": dict(sorted(counts.items())),
        "weighted_finding_points": weighted_points,
        "normalization_denominator": denominator,
        "finding_density": density,
        "raw_penalty": density * policy.density_scale,
        "capped_penalty": penalty,
        "vale_quality_score": quality_score,
        "documentation_score": final_score,
        "documentation_score_policy": DOCUMENTATION_POLICY_REVISION,
        "documentation_components": {
            "completeness": completeness,
            "instructions": instructions,
            "vale_quality": quality_score,
            "readability": readability,
            "weights": {
                "completeness": 0.40,
                "instructions": 0.20,
                "vale_quality": 0.25,
                "readability": 0.15,
            },
            "presence": presence,
        },
        "executable_source": executable_source,
        "policy_revision": policy.revision,
        "policy_digest": policy.digest,
        "metrics_keys": sorted(facts.metrics),
        "threshold_exit_count": facts.threshold_exit_count,
        "threshold_exit_codes": list(facts.threshold_exit_codes),
    }
    log.info(
        "vale_completed",
        analyzer_id=definition.id,
        phase="normalize",
        status=status.value,
        duration_ms=duration_ms,
        discovered_files=len(discovered_files),
        analyzed_files=file_count,
        finding_count=len(findings),
        coverage=coverage,
        score=final_score,
        penalty=penalty,
        failed_batch_count=len(facts.failed_batches),
        policy_revision=facts.policy_revision,
        policy_digest=facts.policy_digest,
    )
    return AnalyzerResult(
        analyzer_id=definition.id,
        analyzer_version=definition.version,
        status=status,
        score=final_score,
        score_dimension="docs",
        metrics=tuple(metrics_rows),
        findings=tuple(generic_findings),
        evidence=tuple({ref.model_dump_json(): ref for ref in evidence}.values()),
        limitations=tuple(limitations),
        duration_ms=duration_ms,
        source_versions=_source_versions(policy),
        available_weight=1,
        total_weight=1,
        raw_payload_ref=_raw_ref(raw_values),
        diagnostics=diagnostics,
    )


class ValeAdapter:
    """Run the official Vale CLI behind the repository-health process port."""

    def __init__(
        self,
        *,
        process: ProcessExecutor | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.process = process or SubprocessProcess()
        self.project_root = Path(project_root or workspace_root()).resolve()

    def _run_process(
        self,
        context: AnalyzerContext,
        executable: Path,
        args: Sequence[str],
        *,
        phase: str,
        timeout: float,
        output_cap: int,
    ) -> ProcessOutput:
        command_fingerprint = hashlib.sha256(
            json.dumps(tuple(str(arg) for arg in args), ensure_ascii=True).encode("utf-8")
        ).hexdigest()[:16]
        log.info(
            "vale_process_started",
            analyzer_id=VALE_ANALYZER_ID,
            phase=phase,
            status="running",
            argument_count=len(args),
            command_fingerprint=command_fingerprint,
            timeout_seconds=timeout,
            output_cap=output_cap,
        )
        output = self.process.run(
            ProcessRequest(
                tool_id=VALE_ANALYZER_ID,
                executable=executable,
                args=tuple(str(arg) for arg in args),
                cwd=context.repo_path.resolve(),
                timeout=timeout,
                output_cap=output_cap,
                repository_id=context.repo_id,
                phase=phase,
            )
        )
        log.info(
            "vale_process_completed",
            analyzer_id=VALE_ANALYZER_ID,
            phase=phase,
            status="timeout" if output.timed_out else "completed",
            exit_code=output.exit_code,
            duration_ms=output.duration_ms,
            timed_out=output.timed_out,
            truncated=output.truncated,
            start_error=type(output.start_error).__name__ if output.start_error else None,
            stdout_bytes=len(output.stdout.encode("utf-8", errors="replace")),
            stderr_bytes=len(output.stderr.encode("utf-8", errors="replace")),
        )
        return output

    def run(self, context: AnalyzerContext) -> AnalyzerResult:
        started = time.perf_counter()
        try:
            policy = load_vale_policy(self.project_root)
        except (OSError, ValueError, TypeError, ValePayloadError) as exc:
            fallback = ValePolicy(
                root=self.project_root,
                policy_file=self.project_root / VALE_CONFIG_RELATIVE,
                config_file=self.project_root / VALE_INI_RELATIVE,
                styles_dir=self.project_root / VALE_STYLES_RELATIVE,
                data={},
                digest="",
            )
            log.error(
                "vale_policy_load_failed",
                analyzer_id=VALE_ANALYZER_ID,
                error_type=type(exc).__name__,
            )
            return _failure_result(
                VALE_DEFINITION,
                fallback,
                reason="Vale policy could not be loaded",
                kind="error",
                diagnostics={"failure_kind": "policy_load", "error_type": type(exc).__name__},
            )

        discovered = discover_documentation_files(context.repo_path, policy, context.inventory)
        if not discovered:
            result = _failure_result(
                VALE_DEFINITION,
                policy,
                reason="No supported documentation files were found",
                kind="insufficient_denominator",
                status=AnalyzerStatus.INCONCLUSIVE,
                diagnostics={
                    "failure_kind": "no_documentation",
                    "discovered_files": 0,
                    "analyzed_files": 0,
                    "process_invoked": False,
                    "policy_revision": policy.revision,
                },
            )
            log.info(
                "vale_skipped_no_documentation",
                analyzer_id=VALE_ANALYZER_ID,
                status=result.status.value,
            )
            return result

        resolution = resolve_vale_executable(context, policy)
        if resolution.path is None:
            result = _failure_result(
                VALE_DEFINITION,
                policy,
                reason="Vale executable is not installed or provisioned",
                kind="missing_capability",
                status=AnalyzerStatus.SKIPPED,
                diagnostics={
                    "failure_kind": "vale_missing",
                    "resolution_source": resolution.source,
                    "candidate_count": resolution.candidate_count,
                    "process_invoked": False,
                },
            )
            log.warning("vale_missing", analyzer_id=VALE_ANALYZER_ID, status=result.status.value)
            return result

        batches = batch_documentation_files(
            discovered,
            config_path=policy.config_file,
            max_files=policy.max_files_per_batch,
            max_command_bytes=policy.max_command_bytes,
        )
        all_findings: list[ValeFindingFact] = []
        all_metrics: dict[str, float] = {}
        analyzed: set[str] = set()
        failed_batches: list[Mapping[str, Any]] = []
        raw_values: list[str] = []
        metrics_batches = 0
        metrics_targets = 0
        usable_batches = 0
        threshold_exit_codes: list[int] = []
        for index, batch in enumerate(batches):
            log.info(
                "vale_batch_started",
                analyzer_id=VALE_ANALYZER_ID,
                phase="diagnostics",
                batch_index=index,
                batch_count=len(batches),
                file_count=len(batch),
            )
            diagnostics_args = (
                f"--config={policy.config_file}",
                f"--output={policy.policy.get('output_format') or 'JSON'}",
                *batch,
            )
            diagnostic_output = self._run_process(
                context,
                resolution.path,
                diagnostics_args,
                phase="diagnostics",
                timeout=min(policy.timeout_seconds, VALE_DEFINITION.timeout - 5.0),
                output_cap=policy.output_cap_bytes,
            )
            raw_values.extend((diagnostic_output.stdout, diagnostic_output.stderr))
            if (
                diagnostic_output.exit_code is None
                or diagnostic_output.timed_out
                or diagnostic_output.truncated
                or diagnostic_output.start_error
            ):
                kind, _reason = _process_failure(diagnostic_output)
                failed_batches.append(
                    {
                        "batch_index": index,
                        "phase": "diagnostics",
                        "kind": kind,
                        "exit_code": diagnostic_output.exit_code,
                        "timed_out": diagnostic_output.timed_out,
                        "truncated": diagnostic_output.truncated,
                    }
                )
                continue
            try:
                diagnostic_payload = json.loads(diagnostic_output.stdout)
                batch_findings = parse_diagnostics(diagnostic_payload, context.repo_path)
            except (json.JSONDecodeError, ValePayloadError, TypeError, ValueError) as exc:
                failed_batches.append(
                    {
                        "batch_index": index,
                        "phase": "diagnostics",
                        "kind": "error",
                        "error_type": type(exc).__name__,
                        "exit_code": diagnostic_output.exit_code,
                    }
                )
                continue
            if diagnostic_output.exit_code:
                threshold_exit_codes.append(diagnostic_output.exit_code)

            successful_metric_files: set[str] = set()
            metrics_targets += len(batch)
            for file in batch:
                metrics_args = (
                    "ls-metrics",
                    f"--config={policy.config_file}",
                    f"--output={policy.policy.get('output_format') or 'JSON'}",
                    file,
                )
                metrics_output = self._run_process(
                    context,
                    resolution.path,
                    metrics_args,
                    phase="metrics",
                    timeout=min(policy.timeout_seconds, VALE_DEFINITION.timeout - 5.0),
                    output_cap=policy.output_cap_bytes,
                )
                raw_values.extend((metrics_output.stdout, metrics_output.stderr))
                if (
                    metrics_output.exit_code is None
                    or metrics_output.timed_out
                    or metrics_output.truncated
                    or metrics_output.start_error
                ):
                    kind, _reason = _process_failure(metrics_output)
                    failed_batches.append(
                        {
                            "batch_index": index,
                            "file": file,
                            "phase": "metrics",
                            "kind": kind,
                            "exit_code": metrics_output.exit_code,
                            "timed_out": metrics_output.timed_out,
                            "truncated": metrics_output.truncated,
                        }
                    )
                    continue
                try:
                    file_metrics = parse_metrics(json.loads(metrics_output.stdout))
                except (json.JSONDecodeError, ValePayloadError, TypeError, ValueError) as exc:
                    failed_batches.append(
                        {
                            "batch_index": index,
                            "file": file,
                            "phase": "metrics",
                            "kind": "error",
                            "error_type": type(exc).__name__,
                            "exit_code": metrics_output.exit_code,
                        }
                    )
                    continue
                if metrics_output.exit_code:
                    threshold_exit_codes.append(metrics_output.exit_code)
                successful_metric_files.add(file)
                metrics_batches += 1
                for key, value in file_metrics.items():
                    all_metrics[key] = all_metrics.get(key, 0.0) + value

            if successful_metric_files:
                usable_batches += 1
                analyzed.update(successful_metric_files)
                all_findings.extend(
                    item for item in batch_findings if item.file in successful_metric_files
                )

        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        if usable_batches == 0:
            first = failed_batches[0] if failed_batches else {"kind": "error"}
            kind = str(first.get("kind") or "error")
            reason = "Vale did not produce a usable diagnostics and metrics result"
            result = _failure_result(
                VALE_DEFINITION,
                policy,
                reason=reason,
                kind=kind,
                raw_ref=_raw_ref(raw_values),
                diagnostics={
                    "failure_kind": kind,
                    "failed_batches": [dict(item) for item in failed_batches],
                    "batch_count": len(batches),
                    "resolution_source": resolution.source,
                    "duration_ms": duration_ms,
                },
            )
            log.error(
                "vale_failed",
                analyzer_id=VALE_ANALYZER_ID,
                status=result.status.value,
                failure_kind=kind,
                duration_ms=duration_ms,
            )
            return result

        return _build_result(
            context,
            policy,
            definition=VALE_DEFINITION,
            discovered_files=discovered,
            analyzed_files=tuple(sorted(analyzed)),
            findings=tuple(all_findings),
            metrics=all_metrics,
            failed_batches=tuple(failed_batches),
            metrics_batches=metrics_batches,
            metrics_targets=metrics_targets,
            total_batches=len(batches),
            successful_batches=usable_batches,
            duration_ms=duration_ms,
            raw_values=raw_values,
            executable_source=resolution.source,
            threshold_exit_codes=threshold_exit_codes,
        )


def vale_adapter(context: AnalyzerContext) -> AnalyzerResult:
    """Registry factory for the Vale analyzer."""
    return ValeAdapter().run(context)


def register_vale_adapter(registry: Any) -> None:
    """Register Vale idempotently at the health edge."""
    if VALE_DEFINITION.id not in registry.ids():
        registry.register(VALE_DEFINITION, vale_adapter)


__all__ = [
    "VALE_ANALYZER_ID",
    "VALE_DEFINITION",
    "VALE_POLICY_REVISION",
    "VALE_SOURCE_COMMIT",
    "ExecutableResolution",
    "ValeAdapter",
    "ValeFacts",
    "ValeFindingFact",
    "ValePayloadError",
    "ValePolicy",
    "batch_documentation_files",
    "discover_documentation_files",
    "load_vale_policy",
    "parse_diagnostics",
    "parse_metrics",
    "register_vale_adapter",
    "resolve_vale_executable",
    "vale_adapter",
]
