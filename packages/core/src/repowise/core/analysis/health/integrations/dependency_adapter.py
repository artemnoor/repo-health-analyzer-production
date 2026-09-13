"""Dependency facts and graph edges from copied RepoCrunch/CHAOSS parsers."""

from __future__ import annotations

import hashlib
import importlib
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    Limitation,
    MetricValue,
)
from .process import workspace_root

log = structlog.get_logger("dependency.enrichment")

REPOCRUNCH_COMMIT = "12938318a6bd59e30a431ab2582baff5d8673eca"
COLLECTOSS_COMMIT = "339edc520e79dd1728ca19255d94a05a4a107df1"
SOKRATES_COMMIT = "f400eb7235a755146e854a1bf4bd90cbe1ee5086"
DEPENDENCY_ANALYZER_ID = "dependencies.enrichment"
DEPENDENCY_DEFINITION = AnalyzerDefinition(
    id=DEPENDENCY_ANALYZER_ID,
    version="dependency-facts-v1",
    category="dependency-enrichment",
    dimensions=("dependencies", "security", "freshness"),
    requires=("dependency:scan",),
    phase=72,
    cost=35,
    timeout=60,
    cache_policy="read_write",
    source_commit=REPOCRUNCH_COMMIT,
    enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
)


@dataclass(frozen=True)
class DependencyFact:
    """One immutable dependency observation with explicit evidence class."""

    name: str
    manifest_path: str
    package_manager: str
    kind: str
    version: str | None = None
    lockfile: str | None = None
    sbom_ref: str | None = None
    libyear: float | None = None
    vulnerability_refs: tuple[str, ...] = ()
    confidence: float = 1.0
    source: str = "repocrunch"
    source_version: str = REPOCRUNCH_COMMIT
    source_event_ids: tuple[str, ...] = ()
    evidence_fragment: str | None = None
    edge_type: str = "manifest"


@dataclass(frozen=True)
class DependencyEdge:
    source_path: str
    target: str
    edge_type: str
    confidence: float
    evidence_fragment: str
    source_event_id: str | None = None


def _repocrunch_source() -> Path:
    source = workspace_root() / "vendor" / "repocrunch" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def copied_dependency_parsers() -> tuple[str, ...]:
    """Return the copied parser modules that are importable in this runtime."""
    try:
        _repocrunch_source()
        module = importlib.import_module("repocrunch.parsers")
    except (ImportError, OSError):
        return ()
    names = (
        "parse_build_gradle",
        "parse_cargo_toml",
        "parse_cmakelists",
        "parse_gemfile",
        "parse_go_mod",
        "parse_package_json",
        "parse_pom_xml",
        "parse_pyproject_toml",
        "parse_requirements_txt",
    )
    return tuple(name for name in names if callable(getattr(module, name, None)))


def _float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _manager(path: str, explicit: object = None) -> str:
    if explicit:
        return str(explicit)
    lower = path.casefold()
    for marker, manager in (
        ("pyproject.toml", "python"),
        ("requirements", "pip"),
        ("package.json", "npm"),
        ("cargo.toml", "cargo"),
        ("go.mod", "go"),
        ("pom.xml", "maven"),
        ("build.gradle", "gradle"),
        ("gemfile", "bundler"),
        ("cmakelists.txt", "cmake"),
    ):
        if marker in lower:
            return manager
    return "unknown"


def _lockfile_for(path: str, row: Mapping[str, Any], inventory: Mapping[str, Any]) -> str | None:
    explicit = row.get("lockfile")
    if isinstance(explicit, str):
        return explicit
    if explicit is True:
        return f"{path}:lockfile"
    values = inventory.get("lockfiles")
    if isinstance(values, Mapping):
        value = values.get(path)
        if isinstance(value, str):
            return value
        values = values.values()
    if isinstance(values, Iterable) and not isinstance(values, (str, bytes)):
        lockfiles = [str(value.get("path") if isinstance(value, Mapping) else value) for value in values]
        stem = Path(path).stem.casefold()
        matches = [value for value in lockfiles if stem in value.casefold() or Path(value).stem.casefold() in {"lock", "package-lock", "pnpm-lock", "yarn", "poetry", "gemfile", "cargo"}]
        if matches:
            return sorted(matches)[0]
    lower = path.casefold()
    defaults = {
        "pyproject.toml": ("poetry.lock", "uv.lock", "pdm.lock"),
        "package.json": ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"),
        "cargo.toml": ("cargo.lock",),
        "gemfile": ("gemfile.lock",),
    }
    for marker, candidates in defaults.items():
        if marker in lower:
            for candidate in candidates:
                if (Path(path).parent / candidate).as_posix() in {str(item) for item in inventory.get("repository_files", ())}:
                    return (Path(path).parent / candidate).as_posix()
    return None


def _sbom_for(name: str, row: Mapping[str, Any], inventory: Mapping[str, Any]) -> str | None:
    if row.get("sbom_ref"):
        return str(row["sbom_ref"])
    refs = inventory.get("sbom_refs")
    if isinstance(refs, Mapping) and refs.get(name):
        return str(refs[name])
    return None


def _vulnerabilities(name: str, row: Mapping[str, Any], inventory: Mapping[str, Any]) -> tuple[str, ...]:
    values = row.get("vulnerability_refs") or row.get("vulnerabilities")
    if values is None and isinstance(inventory.get("vulnerabilities"), Mapping):
        values = inventory["vulnerabilities"].get(name)
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({str(value) for value in values or () if value}))


def _event_id(path: str, name: str, index: int) -> str:
    return f"dependency:{hashlib.sha256(f'{path}:{name}:{index}'.encode()).hexdigest()[:20]}"


def _fact_from_row(row: Mapping[str, Any], index: int, context: AnalyzerContext) -> DependencyFact | None:
    name = row.get("name") or row.get("dep_name") or row.get("package")
    path = row.get("manifest_path") or row.get("manifest_filepath") or row.get("path") or "unknown"
    if not name:
        return None
    kind = str(row.get("kind") or row.get("type") or row.get("scope") or "direct").casefold()
    kind = {"devdependencies": "dev", "dev-dependency": "dev", "testing": "test", "runtimeonly": "runtime"}.get(kind, kind)
    if kind not in {"direct", "dev", "test", "runtime"}:
        kind = "direct"
    confidence = _float(row.get("confidence"))
    return DependencyFact(
        name=str(name),
        manifest_path=str(path),
        package_manager=_manager(str(path), row.get("package_manager")),
        kind=kind,
        version=str(row.get("version") or row.get("current_version") or row.get("current_verion")) if row.get("version") or row.get("current_version") or row.get("current_verion") else None,
        lockfile=str(row.get("lockfile")) if row.get("lockfile") not in (None, False, "") else None,
        sbom_ref=str(row.get("sbom_ref")) if row.get("sbom_ref") else None,
        libyear=_float(row.get("libyear")),
        vulnerability_refs=_vulnerabilities(str(name), row, context.inventory),
        confidence=1.0 if confidence is None else max(0.0, min(1.0, confidence)),
        source=str(row.get("source") or "collectoss"),
        source_version=str(row.get("source_version") or COLLECTOSS_COMMIT),
        source_event_ids=(str(row.get("stable_event_id") or row.get("event_id") or _event_id(str(path), str(name), index)),),
        evidence_fragment=str(row.get("evidence_fragment")) if row.get("evidence_fragment") else None,
        edge_type=str(row.get("edge_type") or "manifest"),
    )


def _parser_result(path: str, content: str) -> tuple[dict[str, list[str]], str | None]:
    _repocrunch_source()
    from repocrunch.parsers import (
        parse_build_gradle,
        parse_cargo_toml,
        parse_cmakelists,
        parse_gemfile,
        parse_go_mod,
        parse_package_json,
        parse_pom_xml,
        parse_pyproject_toml,
        parse_requirements_txt,
    )

    lower = path.casefold()
    if lower.endswith(("build.gradle", "build.gradle.kts")):
        parsed = parse_build_gradle(content)
        return {"direct": parsed.direct, "test": parsed.test}, "gradle"
    if lower.endswith("cargo.toml"):
        parsed = parse_cargo_toml(content)
        return {"direct": parsed.direct, "dev": parsed.dev}, "cargo"
    if lower.endswith("cmakelists.txt"):
        return {"direct": parse_cmakelists(content)}, "cmake"
    if Path(path).name.casefold() == "gemfile":
        parsed = parse_gemfile(content)
        return {"direct": parsed.direct, "dev": parsed.dev}, "bundler"
    if Path(path).name.casefold() == "go.mod":
        return {"runtime": parse_go_mod(content)}, "go"
    if Path(path).name.casefold() == "package.json":
        parsed = parse_package_json(content)
        return {"direct": parsed.direct, "dev": parsed.dev}, parsed.package_manager or "npm"
    if Path(path).name.casefold() == "pom.xml":
        parsed = parse_pom_xml(content)
        return {"direct": parsed.direct, "test": parsed.test}, "maven"
    if Path(path).name.casefold() == "pyproject.toml":
        parsed = parse_pyproject_toml(content)
        return {"direct": parsed.direct, "dev": parsed.dev}, parsed.package_manager or "pip"
    if Path(path).name.casefold().startswith("requirements") and Path(path).suffix.casefold() in {".txt", ".in"}:
        return {"runtime": parse_requirements_txt(content)}, "pip"
    return {}, None


def parse_dependency_facts(context: AnalyzerContext) -> tuple[DependencyFact, ...]:
    """Use explicit CollectOSS rows and copied RepoCrunch manifest parsers."""
    facts: list[DependencyFact] = []
    rows = context.inventory.get("dependency_rows")
    if isinstance(rows, Mapping):
        rows = rows.values()
    if isinstance(rows, Iterable) and not isinstance(rows, (str, bytes)):
        for index, row in enumerate(rows):
            if isinstance(row, Mapping):
                fact = _fact_from_row(row, index, context)
                if fact:
                    facts.append(fact)
    files = context.inventory.get("dependency_files")
    if isinstance(files, Mapping):
        files = (files,)
    if isinstance(files, Iterable) and not isinstance(files, (str, bytes)):
        versions = context.inventory.get("dependency_versions") if isinstance(context.inventory.get("dependency_versions"), Mapping) else {}
        for file_row in files:
            if not isinstance(file_row, Mapping):
                continue
            path = str(file_row.get("path") or file_row.get("manifest_path") or "")
            content = file_row.get("content")
            if content is None and path:
                try:
                    content = (context.repo_path / path).read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    content = None
            if not path or not isinstance(content, str):
                continue
            try:
                parsed, package_manager = _parser_result(path, content)
            except (ImportError, OSError, ValueError, TypeError) as exc:
                log.error("manifest_parse_failed manifest=%s error_type=%s", path, type(exc).__name__)
                continue
            lockfile = _lockfile_for(path, file_row, context.inventory)
            for index, (kind, names) in enumerate(sorted(parsed.items())):
                for name in names:
                    version = versions.get(name) if isinstance(versions, Mapping) else None
                    facts.append(
                        DependencyFact(
                            name=str(name),
                            manifest_path=path,
                            package_manager=package_manager or _manager(path),
                            kind=kind,
                            version=str(version) if version else None,
                            lockfile=lockfile,
                            sbom_ref=str(file_row.get("sbom_ref")) if file_row.get("sbom_ref") else _sbom_for(str(name), file_row, context.inventory),
                            libyear=_float(file_row.get("libyear")),
                            vulnerability_refs=_vulnerabilities(str(name), file_row, context.inventory),
                            source="repocrunch",
                            source_version=REPOCRUNCH_COMMIT,
                            source_event_ids=(_event_id(path, str(name), index),),
                            evidence_fragment=f"{path}:{kind}:{name}",
                            edge_type="manifest",
                        )
                    )
    log.info("dependency_facts_built repo_id=%s facts=%d parsers=%s", context.repo_id, len(facts), copied_dependency_parsers())
    return tuple(facts)


def dependency_edges(context: AnalyzerContext) -> tuple[DependencyEdge, ...]:
    supplied = context.inventory.get("dependency_edges")
    edges: list[DependencyEdge] = []
    if isinstance(supplied, Iterable) and not isinstance(supplied, (str, bytes, Mapping)):
        for index, row in enumerate(supplied):
            if not isinstance(row, Mapping) or not row.get("target"):
                continue
            edge_type = str(row.get("edge_type") or row.get("type") or "heuristic")
            confidence = _float(row.get("confidence"))
            if confidence is None:
                confidence = 1.0 if edge_type in {"ast", "import", "imported", "sokrates"} else 0.6
            edges.append(
                DependencyEdge(
                    source_path=str(row.get("source_path") or row.get("path") or "unknown"),
                    target=str(row["target"]),
                    edge_type=edge_type,
                    confidence=max(0.0, min(1.0, confidence)),
                    evidence_fragment=str(row.get("evidence_fragment") or row.get("fragment") or f"{row.get('source_path', 'unknown')} -> {row['target']}"),
                    source_event_id=str(row.get("source_event_id") or row.get("event_id") or f"edge:{index}"),
                )
            )
    return tuple(edges)


def _evidence(context: AnalyzerContext, fact: DependencyFact) -> EvidenceRef:
    fragment_hash = hashlib.sha256((fact.evidence_fragment or fact.name).encode()).hexdigest()
    return EvidenceRef(
        source=fact.source,
        source_commit=fact.source_version,
        path=fact.manifest_path,
        snippet_hash=fragment_hash,
        json_pointer=f"/dependencies/{fact.name}",
        collected_at=context.as_of_ts,
        confidence=fact.confidence,
        redaction="partial",
    )


def _edge_cycle_count(edges: Iterable[DependencyEdge]) -> int:
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        graph[edge.source_path].add(edge.target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> int:
        if node in visiting:
            return 1
        if node in visited:
            return 0
        visiting.add(node)
        count = sum(visit(child) for child in graph.get(node, ()))
        visiting.remove(node)
        visited.add(node)
        return count

    return sum(visit(node) for node in graph)


class DependencyAdapter:
    definition = DEPENDENCY_DEFINITION

    def result(self, context: AnalyzerContext) -> AnalyzerResult:
        facts = parse_dependency_facts(context)
        edges = dependency_edges(context)
        evidence = tuple(_evidence(context, fact) for fact in facts)
        by_kind = Counter(fact.kind for fact in facts)
        with_lock = sum(bool(fact.lockfile) for fact in facts)
        with_sbom = sum(bool(fact.sbom_ref) for fact in facts)
        libyears = [fact.libyear for fact in facts if fact.libyear is not None]
        vulnerabilities = [fact for fact in facts if fact.vulnerability_refs]
        metrics = (
            MetricValue(name="dependencies:count", dimension="dependencies", value=len(facts), unit="dependencies", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:direct", dimension="dependencies", value=by_kind["direct"], unit="dependencies", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:runtime", dimension="dependencies", value=by_kind["runtime"], unit="dependencies", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:dev", dimension="dependencies", value=by_kind["dev"], unit="dependencies", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:test", dimension="dependencies", value=by_kind["test"], unit="dependencies", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:lockfile_coverage", dimension="dependencies", value=with_lock / len(facts) if facts else None, unit="ratio", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:sbom_coverage", dimension="dependencies", value=with_sbom / len(facts) if facts else None, unit="ratio", denominator=len(facts), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:libyear", dimension="dependencies", value=sum(libyears) if libyears else None, unit="years", denominator=len(libyears), evidence_refs=evidence[:1]),
            MetricValue(name="dependencies:graph_edges", dimension="dependencies", value=len(edges), unit="edges", denominator=len(edges), evidence_refs=evidence[:1]),
        )
        findings: list[Finding] = []
        for index, fact in enumerate(vulnerabilities):
            findings.append(
                Finding(
                    id=f"{DEPENDENCY_ANALYZER_ID}:vulnerability:{fact.name}:{index}",
                    analyzer_id=DEPENDENCY_ANALYZER_ID,
                    subject=fact.name,
                    dimension="security",
                    severity="high",
                    confidence=fact.confidence,
                    reason=f"Dependency has vulnerability references: {', '.join(fact.vulnerability_refs)}",
                    evidence_refs=(_evidence(context, fact),),
                    remediation="Review the lockfile/SBOM finding and upgrade or constrain the affected dependency.",
                )
            )
        for index, edge in enumerate(edges):
            if edge.confidence < 0.9:
                findings.append(
                    Finding(
                        id=f"{DEPENDENCY_ANALYZER_ID}:heuristic-edge:{index}",
                        analyzer_id=DEPENDENCY_ANALYZER_ID,
                        subject=edge.target,
                        dimension="dependencies",
                        severity="medium",
                        confidence=edge.confidence,
                        reason="Dependency graph edge came from a path/name heuristic and needs confirmation.",
                        evidence_refs=(EvidenceRef(source="repowise.dependency-edge", path=edge.source_path, snippet_hash=hashlib.sha256(edge.evidence_fragment.encode()).hexdigest(), collected_at=context.as_of_ts, confidence=edge.confidence, redaction="partial"),),
                        remediation="Confirm the import edge and replace the heuristic dependency reference with a parsed manifest or AST edge.",
                    )
                )
        cycles = _edge_cycle_count(edges)
        if cycles:
            findings.append(
                Finding(
                    id=f"{DEPENDENCY_ANALYZER_ID}:cycles",
                    analyzer_id=DEPENDENCY_ANALYZER_ID,
                    subject="dependency-graph",
                    dimension="dependencies",
                    severity="medium",
                    confidence=0.8,
                    reason=f"Dependency graph contains {cycles} cycle(s).",
                    remediation="Break the dependency cycle by introducing an interface or moving the shared dependency to a lower layer.",
                )
            )
        status = AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS if facts or edges else AnalyzerStatus.INCONCLUSIVE
        limitation = () if facts or edges else (Limitation(reason="No dependency manifests, rows or graph edges were supplied", kind="insufficient_denominator"),)
        return AnalyzerResult(
            analyzer_id=DEPENDENCY_ANALYZER_ID,
            analyzer_version=DEPENDENCY_DEFINITION.version,
            status=status,
            metrics=metrics if facts or edges else (),
            findings=tuple(findings),
            evidence=evidence,
            limitations=limitation,
            source_versions={"repocrunch": REPOCRUNCH_COMMIT, "collectoss": COLLECTOSS_COMMIT, "sokrates": SOKRATES_COMMIT},
            available_weight=float(len(metrics) if facts or edges else 0),
            total_weight=float(len(metrics)),
            diagnostics={
                "raw_fact_count": len(facts),
                "edge_count": len(edges),
                "cycle_count": cycles,
                "provenance": [
                    {
                        "name": fact.name,
                        "manifest_path": fact.manifest_path,
                        "source_event_ids": fact.source_event_ids,
                        "source_version": fact.source_version,
                        "confidence": fact.confidence,
                        "edge_type": fact.edge_type,
                    }
                    for fact in facts
                ],
                "edge_provenance": [edge.__dict__ for edge in edges],
            },
        )


def dependency_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return DependencyAdapter().result(context)


def register_dependency_adapters(registry: Any) -> None:
    if DEPENDENCY_ANALYZER_ID not in registry.ids():
        registry.register(DEPENDENCY_DEFINITION, dependency_adapter)


__all__ = [
    "COLLECTOSS_COMMIT",
    "DEPENDENCY_ANALYZER_ID",
    "DEPENDENCY_DEFINITION",
    "DependencyAdapter",
    "DependencyEdge",
    "DependencyFact",
    "copied_dependency_parsers",
    "dependency_adapter",
    "dependency_edges",
    "parse_dependency_facts",
    "register_dependency_adapters",
]
