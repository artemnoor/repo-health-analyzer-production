"""Prove that a drifted temporary source ledger fails before a build."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import vendor_sources

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("health.source-update")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    original_path = vendor_sources.LEDGER_PATH
    payload = json.loads(original_path.read_text(encoding="utf-8"))
    payload["sources"][0]["commit"] = "0" * 40
    with tempfile.TemporaryDirectory(prefix="repository-health-ledger-") as temp:
        temporary_path = Path(temp) / "SOURCES.lock"
        temporary_path.write_text(json.dumps(payload), encoding="utf-8")
        vendor_sources.LEDGER_PATH = temporary_path
        try:
            result = vendor_sources.verify()
        finally:
            vendor_sources.LEDGER_PATH = original_path
    if result == 0:
        LOG.error("source-update simulation unexpectedly passed")
        return 1
    LOG.info("source-update simulation passed: drifted temporary ledger rejected before build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
