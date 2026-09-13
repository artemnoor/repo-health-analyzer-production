from __future__ import annotations

import json
import re
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def test_source_ledger_entries_have_unique_targets_and_existing_sentinels() -> None:
    root = Path(__file__).resolve().parents[2]
    ledger = json.loads((root / "vendor/SOURCES.lock").read_text(encoding="utf-8"))
    entries = ledger["sources"]

    executable = [entry for entry in entries if entry["copy_mode"] != "reference-only"]
    targets = [entry["target_root"] for entry in executable]
    assert len(targets) == len(set(targets))

    for entry in entries:
        assert entry["runtime"]
        assert entry["build"]
        assert entry["test"]
        if entry["copy_mode"] == "reference-only":
            assert entry["commit"] is None
            assert entry["target_root"] is None
            continue

        assert SHA_RE.fullmatch(entry["commit"])
        assert (root / entry["source_root"]).exists()
        assert (root / entry["target_root"]).exists()
        for sentinel in entry["sentinels"]:
            assert (root / entry["target_root"] / sentinel).exists(), (entry["name"], sentinel)
