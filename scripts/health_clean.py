"""Remove only generated Repository Health report files."""

from __future__ import annotations

import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("health.clean")
ALLOWED = (ROOT / ".repowise" / "health-latest.json", ROOT / "artifacts" / "health-sample.json")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    for path in ALLOWED:
        if path.is_file():
            path.unlink()
            LOG.info("removed generated report path=%s", path.relative_to(ROOT))
        else:
            LOG.debug("already absent path=%s", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
