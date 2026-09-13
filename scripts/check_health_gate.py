"""Apply the Repository Health CI policy to a redacted JSON report."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

LOG = logging.getLogger("health.gate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    results = payload.get("analyzer_results", [])
    for item in results:
        if not isinstance(item, dict):
            continue
        score = item.get("score", item.get("overall_score"))
        if score is not None and (not isinstance(score, (int, float)) or not 0 <= score <= 100):
            LOG.error("health gate invalid score status=%s", item.get("status", "unknown"))
            return 1
    statuses = Counter(
        str(item.get("status", "unknown")) for item in results if isinstance(item, dict)
    )
    for status in ("skipped", "inconclusive", "error"):
        if statuses[status]:
            LOG.warning("status=%s count=%d policy=visible-not-pass", status, statuses[status])
    failures = statuses["fail"]
    LOG.info(
        "health gate report=%s statuses=%s fail_on=fail",
        args.report,
        dict(sorted(statuses.items())),
    )
    if failures:
        LOG.error("health gate failed fail_count=%d", failures)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
