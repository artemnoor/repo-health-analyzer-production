#!/usr/bin/env python3
"""Validate Repo Health cleanup/legal inventory without mutating the checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "research" / "archive" / "repo-health-external-dependencies.json"
SOURCES = ROOT / "vendor" / "SOURCES.lock"

REQUIRED_SPIKES = {"Doc Detective", "Schemathesis", "Hercules", "OpenDigger", "Apache DevLake"}
SOURCE_ALIASES = {
    "grimoirelab": "chaoss-grimoirelab-family",
    "grimoirelab-perceval": "chaoss-grimoirelab-family",
    "grimoirelab-elk": "chaoss-grimoirelab-family",
    "grimoirelab-sortinghat": "chaoss-grimoirelab-family",
    "grimoirelab-sirmordred": "chaoss-grimoirelab-family",
    "grimoirelab-graal": "chaoss-grimoirelab-family",
    "grimoirelab-sigils": "chaoss-grimoirelab-family",
}


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _resolve(relative: str) -> Path:
    return ROOT / Path(relative.replace("/", "\\"))


def _check_wheel(path: Path) -> list[str]:
    from zipfile import ZipFile

    errors: list[str] = []
    try:
        with ZipFile(path) as archive:
            forbidden = tuple(name for name in archive.namelist() if any(
                name.startswith(prefix)
                for prefix in ("vendor/", "spikes/", "$out/", "tests/", "scripts/")
            ))
    except (OSError, ValueError) as exc:
        return [f"wheel: cannot inspect {path}: {exc}"]
    if forbidden:
        errors.append(f"wheel contains forbidden production paths: {forbidden[:5]}")
    return errors


def verify(*, wheel: Path | None = None, strict: bool = False) -> tuple[list[str], list[str]]:
    matrix = _load(MATRIX)
    sources = _load(SOURCES)
    entries = matrix.get("entries")
    source_entries = sources.get("sources")
    if not isinstance(entries, list) or not entries:
        return ["dependency matrix has no entries"], []
    if not isinstance(source_entries, list) or not source_entries:
        return ["vendor/SOURCES.lock has no sources"], []

    errors: list[str] = []
    warnings: list[str] = []
    by_name = {str(entry.get("name")): entry for entry in entries if isinstance(entry, dict)}
    missing_spikes = REQUIRED_SPIKES - set(by_name)
    if missing_spikes:
        errors.append(f"named spike dependencies missing from matrix: {sorted(missing_spikes)}")

    for source in source_entries:
        if not isinstance(source, dict):
            errors.append("vendor/SOURCES.lock contains a non-object source entry")
            continue
        name = str(source.get("name"))
        if source.get("copy_mode") == "reference-only":
            continue
        matrix_name = SOURCE_ALIASES.get(name, name)
        if matrix_name not in by_name:
            errors.append(f"SOURCES.lock source is unclassified: {name}")

    for name, entry in by_name.items():
        local_path = str(entry.get("local_path", ""))
        if (
            local_path
            and not local_path.startswith("external")
            and not any(marker in local_path for marker in ("{", "}", "*", "[", "]"))
            and not _resolve(local_path).exists()
        ):
            warnings.append(f"{name}: local path is absent or intentionally external: {local_path}")
        notice_paths = entry.get("notice_paths", [])
        if not isinstance(notice_paths, list):
            errors.append(f"{name}: notice_paths must be an array")
            continue
        for notice in notice_paths:
            notice_text = str(notice)
            if any(marker in notice_text for marker in ("*", "{", "}")):
                continue
            notice_path = _resolve(notice_text)
            if not notice_path.exists():
                warnings.append(f"{name}: notice/provenance path is absent: {notice_text}")
        for field in ("integration_mode", "classification", "production_required", "can_delete_local_copy"):
            if not entry.get(field):
                errors.append(f"{name}: missing matrix field {field}")

    missing_sources = [
        str(source.get("source_root"))
        for source in source_entries
        if isinstance(source, dict)
        and source.get("copy_mode") != "reference-only"
        and not _resolve(str(source.get("source_root"))).exists()
    ]
    if missing_sources:
        warnings.append(
            "provenance gate blocked by missing source roots: "
            + ", ".join(missing_sources)
        )
        if strict:
            errors.append("strict mode: missing .sources roots prevent legal verification")

    if wheel is not None:
        errors.extend(_check_wheel(wheel))
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="inspect a built wheel for forbidden source/artifact roots")
    parser.add_argument("--strict", action="store_true", help="fail when .sources provenance roots are missing")
    args = parser.parse_args()
    try:
        errors, warnings = verify(wheel=args.wheel, strict=args.strict)
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    result = {
        "status": "failed" if errors else "verified",
        "matrix": str(MATRIX.relative_to(ROOT)).replace("\\", "/"),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
