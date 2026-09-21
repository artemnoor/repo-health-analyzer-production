"""Verify Repo Health contract and module-boundary invariants.

This checker is intentionally dependency-light and operates on the standalone
``src/repo_health`` tree. Target modules must not grow imports across transport,
persistence, provider or analyzer boundaries.
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import sys
from pathlib import Path

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(levelname)s %(message)s")
log = logging.getLogger("repo_health.verify_contracts")

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "repo_health"

FORBIDDEN_PREFIXES = (
    "fastapi",
    "sqlalchemy",
    "vendor",
)
FORBIDDEN_PROVIDER_MARKERS = ("raw_payload", "sourcecraft_payload", "provider_response")
CANONICAL_IDS = {
    "repo-health.documentation",
    "repo-health.activity",
    "repo-health.issues",
    "repo-health.cicd",
    "repo-health.security",
    "repo-health.code-health",
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(TARGET).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return "repo_health" + ("." + ".".join(parts) if parts else "")


def _imports(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append("." * node.level + (node.module or ""))
            elif node.module:
                found.append(node.module)
    return found


def verify_imports(*, no_provider_payloads: bool = False, analyzer_isolation: bool = False) -> int:
    failures: list[str] = []
    if not TARGET.exists():
        failures.append(f"target package does not exist: {TARGET}")
    for path in sorted(TARGET.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path}: syntax error: {exc}")
            continue
        module = _module_name(path)
        imports = _imports(tree)
        for imported in imports:
            if imported.startswith("fastapi"):
                if not module.startswith("repo_health.api"):
                    failures.append(f"{path}: FastAPI import outside API boundary {imported}")
            elif imported.startswith(FORBIDDEN_PREFIXES):
                failures.append(f"{path}: forbidden import {imported}")
            if (
                analyzer_isolation
                and module.startswith("repo_health.analyzers.")
                and imported.startswith("repo_health.analyzers.")
                and imported != module
            ):
                failures.append(f"{path}: analyzer-to-analyzer import {imported}")
        if no_provider_payloads:
            source = path.read_text(encoding="utf-8").casefold()
            for marker in FORBIDDEN_PROVIDER_MARKERS:
                if marker in source:
                    failures.append(f"{path}: provider payload marker {marker}")
    if failures:
        for failure in failures:
            log.error(failure)
        return 1
    log.info("contract import checks passed for %s", TARGET)
    return 0


def verify_registry() -> int:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from repo_health.analyzers.registry import canonical_registry

        canonical_registry.validate()
        actual = set(canonical_registry.ids())
    except Exception as exc:  # pragma: no cover - command-line diagnostic
        log.error("registry validation failed: %s", exc)
        return 1
    if actual != CANONICAL_IDS:
        log.error("registry IDs differ; expected=%s actual=%s", sorted(CANONICAL_IDS), sorted(actual))
        return 1
    log.info("canonical registry contains exactly six analyzers")
    return 0


def verify_facts(*, deterministic: bool = False, redaction: bool = False) -> int:
    """Run small fact-contract checks without requiring a provider or checkout."""
    if not deterministic and not redaction:
        return 0
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from repo_health.contracts.requests import RepositoryRef
        from repo_health.contracts.results import IssuesFacts, RepositoryFacts

        repository = RepositoryRef(
            repository_id="verify/repository",
            canonical_uri="https://sourcecraft.example/verify/repository",
            provider="sourcecraft",
            head_sha="a" * 40,
        )
        facts = RepositoryFacts(
            repository=repository,
            issues=IssuesFacts(observations=({"key": "open_count", "value": 1},)),
        )
        if deterministic and facts.digest() != facts.model_copy().digest():
            raise ValueError("facts digest is not deterministic")
        if redaction and any(secret in facts.to_json().casefold() for secret in ("token", "password", "c:\\users")):
            raise ValueError("fact serialization contains redaction marker input")
    except Exception as exc:  # pragma: no cover - command-line diagnostic
        log.error("facts verification failed: %s", exc)
        return 1
    log.info("fact contract checks passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imports", action="store_true", help="check target import direction")
    parser.add_argument("--registry", action="store_true", help="check the canonical six-entry registry")
    parser.add_argument(
        "--analyzer-isolation",
        "--no-cross-analyzer-imports",
        dest="analyzer_isolation",
        action="store_true",
        help="reject analyzer-to-analyzer imports",
    )
    parser.add_argument("--no-provider-payloads", action="store_true", help="reject raw provider payload markers")
    parser.add_argument("--facts-deterministic", action="store_true", help="check normalized facts digest determinism")
    parser.add_argument("--redaction", action="store_true", help="check fact serialization redaction gate")
    parser.add_argument("--all", action="store_true", help="run every check")
    args = parser.parse_args(argv)
    run_imports = args.imports or args.all or args.analyzer_isolation or args.no_provider_payloads
    run_registry = args.registry or args.all or not run_imports
    result = 0
    if run_imports:
        result |= verify_imports(
            no_provider_payloads=args.no_provider_payloads or args.all,
            analyzer_isolation=args.analyzer_isolation or args.all,
        )
    if run_registry:
        result |= verify_registry()
    result |= verify_facts(
        deterministic=args.facts_deterministic or args.all,
        redaction=args.redaction or args.all,
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
