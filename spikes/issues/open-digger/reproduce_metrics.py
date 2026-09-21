"""Small, dependency-free reproduction of OpenDigger's issue algorithms.

This is deliberately a methodology check, not a claim about fixture issue
data. OpenDigger's runtime normally queries ClickHouse GitHub event rows; the
repository fixture has no issue-event export, so this script uses the adjacent
synthetic_events.json only to make the transformations executable and
reviewable.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def day_diff(left: datetime, right: datetime) -> int:
    # OpenDigger uses ClickHouse dateDiff('day', ...), i.e. calendar-day
    # boundaries rather than fractional elapsed days.
    return (right.date() - left.date()).days


def quantile(values: list[int | float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + fraction * (ordered[upper] - ordered[lower]), 3)


def summary(values: list[int | float], thresholds: list[int]) -> dict[str, object]:
    ranges = [*thresholds, -1]
    levels = [0 for _ in ranges]
    for value in values:
        level = next((index for index, threshold in enumerate(thresholds) if value <= threshold), len(thresholds))
        levels[level] += 1
    return {
        "count": len(values),
        "values": values,
        "avg": round(statistics.fmean(values), 3),
        "levels": levels,
        "quantiles": {f"quantile_{index}": quantile(values, index / 4) for index in range(5)},
    }


def main() -> int:
    input_path = Path(__file__).with_name("synthetic_events.json")
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runs/reproduced.json")
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        row["time"] = parse(str(row["created_at"]))
        row["opened_time"] = parse(str(row["issue_created_at"]))
        grouped[int(row["issue_id"])].append(row)

    response_values: list[int] = []
    resolution_values: list[int] = []
    issue_records: list[dict[str, object]] = []
    for issue_id, events in sorted(grouped.items()):
        events.sort(key=lambda row: row["time"])
        opened = min((row["opened_time"] for row in events), default=None)
        if opened is None:
            continue
        # Source filter: actor_login NOT LIKE '%[bot]' for response time.
        response_events = [row for row in events if "[bot]" not in str(row["actor_login"])]
        responded = [
            row["time"]
            for row in response_events
            if (row["action"] == "created" and row["actor_id"] != row["issue_author_id"])
            or row["action"] == "closed"
        ]
        first_responded = min(responded, default=opened + timedelta(days=15))
        response_days = day_diff(opened, first_responded)
        response_values.append(response_days)

        closed = [row["time"] for row in events if row["action"] == "closed"]
        last_closed = max(closed, default=None)
        resolution_days = day_diff(opened, last_closed) if last_closed else None
        if resolution_days is not None:
            resolution_values.append(resolution_days)
        issue_records.append(
            {
                "issue_id": issue_id,
                "response_days": response_days,
                "resolution_days": resolution_days,
                "first_response_actor": next(
                    (row["actor_login"] for row in response_events if row["time"] == first_responded),
                    "synthetic-fallback",
                ),
            }
        )

    reference_time = datetime(2026, 1, 5, tzinfo=timezone.utc)
    ages: list[int] = []
    for issue_id, events in sorted(grouped.items()):
        opened = min(row["opened_time"] for row in events)
        closed = [row["time"] for row in events if row["action"] == "closed"]
        closed_at = max(closed, default=reference_time)
        if opened < reference_time and closed_at >= reference_time:
            ages.append(day_diff(opened, reference_time))

    result = {
        "tool": "OpenDigger algorithm reproduction",
        "status": "METHODOLOGY_ONLY",
        "fixture_issue_events": "unavailable",
        "synthetic_input": str(input_path.as_posix()),
        "source_sha": "63e4b89ecd525221be95fe2a48a714ebb3c722ec",
        "source_paths": ["src/metrics/chaoss.ts", "src/metrics/basic.ts"],
        "response_time_days": summary(response_values, [3, 7, 15]),
        "resolution_time_days": summary(resolution_values, [3, 7, 15]),
        "issue_age_days_at_2026_01_05": summary(ages, [15, 30, 60]),
        "issue_records": issue_records,
        "bot_filter_check": {
            "bot_actor_ignored_for_response": "dependabot[bot]",
            "human_first_response_actors": [record["first_response_actor"] for record in issue_records],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
