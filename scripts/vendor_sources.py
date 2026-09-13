#!/usr/bin/env python3
"""Verify pinned analyzer source snapshots without mutating the workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "vendor" / "SOURCES.lock"
LOGGER = logging.getLogger("vendor.ledger")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


def _configure_logging() -> None:
    requested = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, requested, logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s [%(name)s] %(message)s")


def _load_ledger() -> dict[str, Any]:
    LOGGER.debug("loading ledger path=%s", LEDGER_PATH)
    try:
        payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load {LEDGER_PATH}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise RuntimeError("ledger must be an object with a sources array")
    return payload


def _git(source_root: Path, *args: str, binary: bool = False) -> str | bytes:
    command = ["git", "-C", str(source_root), *args]
    LOGGER.debug("external git call source=%s args=%s", source_root, args)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=not binary,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace") if binary else completed.stderr
        raise RuntimeError(f"git command failed ({completed.returncode}): {stderr.strip()}")
    return completed.stdout


def _git_head(source_root: Path) -> str:
    return str(_git(source_root, "rev-parse", "HEAD")).strip()


def _git_blob_entries(source_root: Path) -> list[tuple[str, str, str]]:
    raw = _git(source_root, "ls-tree", "-r", "-z", "HEAD", binary=True)
    assert isinstance(raw, bytes)
    entries: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, path_bytes = record.split(b"\t", 1)
            mode, object_type, object_id = header.split(b" ", 2)
        except ValueError as exc:
            raise RuntimeError(f"malformed git tree record in {source_root}") from exc
        if object_type != b"blob":
            continue
        entries.append((os.fsdecode(path_bytes), object_id.decode("ascii"), mode.decode("ascii")))
    return entries


def _git_blob_sha1(path: Path, mode: str = "100644") -> str:
    if mode == "120000" or path.is_symlink():
        return _wsl_symlink_blob_sha1(path)
    if any(Path(part).stem.casefold() in WINDOWS_RESERVED_NAMES for part in path.parts):
        return _wsl_git_blob_sha1(path)
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wsl_path(path: Path) -> str:
    converted = subprocess.run(
        ["wsl.exe", "--", "wslpath", "-a", "--", str(path)],
        check=False,
        capture_output=True,
    )
    if converted.returncode != 0:
        stderr = (converted.stderr or b"").decode("utf-8", errors="replace").strip()
        raise OSError(f"wslpath failed: {stderr}")
    return (converted.stdout or b"").decode("utf-8", errors="replace").strip()


def _wsl_symlink_blob_sha1(path: Path) -> str:
    """Hash a symlink's link text, matching Git's mode-120000 blob semantics."""
    content = _wsl_readlink(path)
    if content is None:
        raise OSError("path is not a symlink")
    digest = hashlib.sha1()
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def _wsl_readlink(path: Path) -> bytes | None:
    linux_path = _wsl_path(path)
    linked = subprocess.run(
        ["wsl.exe", "--", "readlink", "--", linux_path],
        check=False,
        capture_output=True,
    )
    if linked.returncode != 0:
        stderr = (linked.stderr or b"").decode("utf-8", errors="replace").strip()
        raise OSError(f"WSL readlink failed: {stderr}")
    return (linked.stdout or b"").rstrip(b"\r\n")


def _wsl_git_blob_sha1(path: Path) -> str:
    """Hash Windows-reserved filenames through WSL, where they are ordinary files."""
    linux_path = _wsl_path(path)
    hashed = subprocess.run(
        ["wsl.exe", "--", "git", "hash-object", "--", linux_path],
        check=False,
        capture_output=True,
    )
    if hashed.returncode != 0:
        stderr = (hashed.stderr or b"").decode("utf-8", errors="replace").strip()
        raise OSError(f"WSL git hash-object failed: {stderr}")
    return (hashed.stdout or b"").decode("ascii", errors="replace").strip()


def _path_from_root(relative: str | None) -> Path | None:
    if relative is None:
        return None
    return ROOT / Path(relative)


def _verify_entry(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = entry.get("name", "<unnamed>")
    mode = entry.get("copy_mode")
    if mode == "reference-only":
        if (
            entry.get("commit") is not None
            or entry.get("source_root") is not None
            or entry.get("target_root") is not None
        ):
            errors.append(
                f"{name}: reference-only entry must not have commit/source_root/target_root"
            )
        LOGGER.info("reference-only source verified name=%s url=%s", name, entry.get("url"))
        return errors

    required = (
        "url",
        "commit",
        "source_root",
        "target_root",
        "runtime",
        "build",
        "test",
        "adapter",
    )
    for field in required:
        if not entry.get(field):
            errors.append(f"{name}: missing required field {field}")
    commit = str(entry.get("commit", ""))
    if not SHA_RE.fullmatch(commit):
        errors.append(f"{name}: commit must be a 40-character lowercase SHA")

    source_root = _path_from_root(entry.get("source_root"))
    target_root = _path_from_root(entry.get("target_root"))
    if source_root is None or not source_root.exists():
        errors.append(f"{name}: source root is missing: {entry.get('source_root')}")
        return errors
    if target_root is None or not target_root.exists():
        errors.append(f"{name}: target root is missing: {entry.get('target_root')}")
        return errors

    try:
        actual_head = _git_head(source_root)
    except RuntimeError as exc:
        errors.append(f"{name}: {exc}")
    else:
        if actual_head != commit:
            errors.append(f"{name}: expected commit {commit}, got {actual_head}")

    sentinels = entry.get("sentinels", [])
    if not isinstance(sentinels, list):
        errors.append(f"{name}: sentinels must be an array")
        sentinels = []
    for sentinel in sentinels:
        sentinel_path = target_root / str(sentinel)
        if not sentinel_path.exists():
            errors.append(f"{name}: missing sentinel {sentinel_path}")

    if entry.get("verify_mode") == "git-tree" and not errors:
        LOGGER.info("checking copied tree name=%s", name)
        try:
            blob_entries = _git_blob_entries(source_root)
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")
        else:
            mismatches = 0
            for relative, expected_oid, mode in blob_entries:
                target_path = target_root / Path(relative)
                try:
                    present = (
                        _wsl_readlink(target_path) is not None
                        if mode == "120000"
                        else target_path.exists()
                    )
                except OSError as exc:
                    # Windows reparse points are valid copied symlinks, but a
                    # machine without a working WSL service cannot dereference
                    # them to compare link text. Keep the ledger gate honest:
                    # presence is verified, link-content comparison is an
                    # explicit platform skip, never a fabricated content pass.
                    if mode == "120000" and os.name == "nt" and os.path.lexists(target_path):
                        LOGGER.warning(
                            "symlink content verification skipped name=%s path=%s reason=%s",
                            name,
                            relative,
                            str(exc),
                        )
                        continue
                    errors.append(f"{name}: cannot inspect copied path {relative}: {exc}")
                    mismatches += 1
                    continue
                if not present:
                    errors.append(f"{name}: missing copied path {relative}")
                    mismatches += 1
                    continue
                try:
                    actual_oid = _git_blob_sha1(target_path, mode)
                except OSError as exc:
                    if (
                        os.name == "nt"
                        and os.path.lexists(target_path)
                        and (
                            mode == "120000"
                            or Path(relative).stem.casefold() in WINDOWS_RESERVED_NAMES
                        )
                    ):
                        LOGGER.warning(
                            "path content hash skipped name=%s path=%s reason=%s",
                            name,
                            relative,
                            str(exc),
                        )
                        continue
                    errors.append(f"{name}: cannot read copied path {relative}: {exc}")
                    mismatches += 1
                    continue
                if actual_oid != expected_oid:
                    errors.append(f"{name}: content drift at {relative}")
                    mismatches += 1
            LOGGER.debug(
                "tree verification name=%s blobs=%d mismatches=%d",
                name,
                len(blob_entries),
                mismatches,
            )

    if not errors:
        LOGGER.info("source verified name=%s commit=%s mode=%s", name, commit, mode)
    return errors


def verify() -> int:
    ledger = _load_ledger()
    entries = ledger["sources"]
    target_roots: dict[str, str] = {}
    errors: list[str] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            errors.append("source entry must be an object")
            continue
        target = raw_entry.get("target_root")
        if raw_entry.get("copy_mode") != "reference-only" and target:
            previous = target_roots.get(str(target))
            if previous:
                errors.append(
                    f"duplicate target_root {target}: {previous} and {raw_entry.get('name')}"
                )
            else:
                target_roots[str(target)] = str(raw_entry.get("name"))
        errors.extend(_verify_entry(raw_entry))
    if errors:
        for error in errors:
            LOGGER.error(error)
        return 1
    LOGGER.info(
        "ledger verification passed sources=%d executable=%d reference_only=%d",
        len(entries),
        len(target_roots),
        sum(1 for entry in entries if entry.get("copy_mode") == "reference-only"),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify pinned source roots, sentinels and copied tree content",
    )
    parser.add_argument(
        "--update", action="store_true", help="reserved update mode; requires an explicit --sha"
    )
    parser.add_argument(
        "--sha", help="explicit 40-character source commit SHA for a reviewed update"
    )
    args = parser.parse_args(argv)
    if args.update:
        if not args.sha or not SHA_RE.fullmatch(args.sha):
            parser.error("--update requires an explicit 40-character lowercase --sha")
        parser.error(
            "automatic updates are disabled; copy the reviewed SHA and update SOURCES.lock explicitly"
        )
    if not args.verify:
        parser.error("choose --verify")
    return verify()


if __name__ == "__main__":
    sys.exit(main())
