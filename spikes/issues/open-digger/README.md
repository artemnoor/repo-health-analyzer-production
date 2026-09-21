# OpenDigger spike

Verdict: **PARTIAL FIT / METHODOLOGY VERIFIED**.

OpenDigger has the requested issue metrics, but it is primarily a data service
and ClickHouse query layer rather than a standalone repository-local CLI. The
fixture has Git history and SourceCraft configuration, but no GitHub/GitLab
issue-event export. Therefore the full service run is not claimed; the metric
transformations were read from the exact source commit and reproduced with a
small executable synthetic event stream.

## Source and license

- Upstream: `https://github.com/X-lab2017/open-digger.git`
- Cloned at: `63e4b89ecd525221be95fe2a48a714ebb3c722ec`
- Version: `1.0.0` (`upstream/package.json`)
- License: Apache-2.0 (`upstream/package.json`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Algorithm study

The relevant implementation is in `upstream/src/metrics/chaoss.ts`:

- `chaossIssueResponseTime` groups issue events, excludes actors whose login
  contains `[bot]`, finds the first non-author comment or close event, and uses
  `dateDiff(unit, issue_created_at, first_responded_at)`. If there is no
  response, source code substitutes 15 days.
- `chaossIssueResolutionDuration` groups issue events by repository, issue, and
  platform, keeps closed issues, computes `dateDiff(unit, opened_at, closed_at)`,
  and returns average, threshold buckets, and quantiles.
- `chaossIssueAge` evaluates each issue at a period boundary and includes it
  when `opened_at < time` and `closed_at >= time`; an issue without a close is
  treated as closing at the end of the requested range.
- Each duration metric requests `quantile(0)`, `quantile(0.25)`,
  `quantile(0.5)`, `quantile(0.75)`, and `quantile(1)` from ClickHouse. The
  default duration buckets are `[3, 7, 15]` for response/resolution and
  `[15, 30, 60]` for age.
- The same module filters `[bot]` actors for response time. Bus-factor logic
  also excludes bot authors unless `withBot` is explicitly enabled.

The underlying event contract is documented in
`upstream/skills/open-digger-clickhouse-schema/events-table-reference.md`;
important fields include `issue_id`, `issue_number`, `issue_author_id`,
`issue_created_at`, `issue_comments`, `created_at`, and actor identity fields.

## Installation attempt and standard boundary

The package has standard Node scripts (`npm run build`, `npm test`), but it
depends on ClickHouse/Neo4j-backed data services. `npm ci` was attempted in the
exact clone and failed after about 36 seconds while the `sharp` postinstall
download of `libvips` timed out. The captured error and cleanup warnings are in
`runs/npm-ci.stderr.log` and `runs/npm-ci.timing`.

The documented service setup uses ClickHouse sample data and Docker. No
ClickHouse or Neo4j service was available in this environment, so no live SQL
query was issued. This is a reproducible infrastructure boundary, not a
fabricated zero result.

## Executable algorithm reproduction

`reproduce_metrics.py` reads `synthetic_events.json` and writes
`runs/reproduced.json`. The data is explicitly synthetic because the fixture
contains no issue events. It covers:

```text
response time:   values [3, 10, 0], avg 4.333,
                 quantiles [0, 1.5, 3, 6.5, 10]
resolution time: values [5, 10, 1], avg 5.333,
                 quantiles [1, 3, 5, 7.5, 10]
issue age:       values [4, 4] at 2026-01-05, avg 4,
                 quantiles [4, 4, 4, 4, 4]
```

The synthetic stream includes a `dependabot[bot]` event. The reproduction
proves that it is ignored when selecting the first response, while a human
response remains visible. The JSON also records the bucket counts and each
issue's intermediate values. Runtime was under 0.3 seconds including Python
startup (`runs/reproduced.timing`).

## Integration boundary and limitations

There are two practical integration paths:

1. query OpenDigger's public precomputed metric JSON for a known platform,
   owner, and repository; or
2. connect an adapter to the ClickHouse `events` table and map the returned
   metric arrays to the analyzer's period model.

The second path needs a large external data service and its data freshness and
coverage assumptions. OpenDigger's own documentation notes that GH Archive
data can be incomplete, so metrics are better treated as trends than exact
ground truth. The first path is simpler but depends on the public endpoint's
availability and metric catalog. Neither path can produce issue metrics from
the current fixture alone.
