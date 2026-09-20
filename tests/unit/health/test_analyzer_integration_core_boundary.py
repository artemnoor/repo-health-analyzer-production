"""Import-boundary regression tests for the neutral analyzer kernel."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT / "packages" / "core" / "src" / "repowise" / "core" / "analysis" / "analyzer_integration"
)

FORBIDDEN_PREFIXES = (
    "repowise.core.analysis.health",
    "repowise.core.ingestion",
    "repowise.core.persistence",
    "repowise.server",
    "repowise.cli",
    "sqlalchemy",
    "GitIndexer",
    "REST",
    "MCP",
    "UI",
    "web",
    "vendor",
    "RepoWise",
    "forge",
    "chaoss",
    "CollectOSS",
    "GrimoireLab",
    "sokrates",
    "Sokrates",
)


def test_neutral_package_imports_without_health_or_adapter_side_effects() -> None:
    source_path = str(ROOT / "packages" / "core" / "src")
    code = f"""
import sys
sys.path.insert(0, {source_path!r})
import importlib
import sys
importlib.import_module('repowise.core.analysis.analyzer_integration')
print('\\n'.join(sorted(sys.modules)))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "packages" / "core" / "src")
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    modules = set(completed.stdout.splitlines())
    assert "repowise.core.analysis.analyzer_integration" in modules
    assert not any(module.startswith(prefix) for module in modules for prefix in FORBIDDEN_PREFIXES)


def test_every_neutral_module_has_no_forbidden_source_imports() -> None:
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(
                name == prefix or name.startswith(f"{prefix}.")
                for name in names
                for prefix in FORBIDDEN_PREFIXES
            ), f"forbidden import in {path}: {names}"


def test_every_neutral_submodule_imports_in_a_clean_interpreter() -> None:
    source_path = str(ROOT / "packages" / "core" / "src")
    modules = sorted(path.stem for path in PACKAGE.glob("*.py") if path.stem != "__init__")
    code = f"""
import sys
sys.path.insert(0, {source_path!r})
for name in {modules!r}:
    __import__('repowise.core.analysis.analyzer_integration.' + name)
"""
    subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, check=True)
