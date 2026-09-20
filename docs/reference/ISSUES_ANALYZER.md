# Issues Analyzer

`chaoss.issues_prs` is the existing Issues/PR analyzer with an additive,
normalized Issues path.  It uses the repository's existing SourceCraft/
CollectOSS-derived inventory.  It does not add a SourceCraft client, GitHub or
GitLab API, OpenDigger service, CHAOSS service, or LLM.

OpenDigger and CHAOSS Metrics are methodology references only.  The pinned
references are OpenDigger revision
`63e4b89ecd525221be95fe2a48a714ebb3c722ec` and CHAOSS Metrics revision
`fae1f4dfc533a6f28499bdba3fb1514ccabc2018`.

## Boundary and ownership

```text
SourceCraft/CollectOSS collector
        |
        | issues, comments, state events, pagination metadata
        v
AnalyzerContext.inventory
        |
        v
issues_facts.normalize_issue_inventory()
        |
        v
IssueCollectionFacts / IssueFact / IssueEventFact
        |
        v
IssuesAnalyzer
        |
        +--> existing legacy PR/aggregate metrics
        +--> one aggregate delivery score
        v
AnalyzerResult for chaoss.issues_prs
```

The collector owns pagination, permissions, local date filtering, raw
timestamps, and source provenance.  The analyzer only consumes already
collected mappings.  Accepted granular inventory keys are `issues`,
`issue_rows`, `issue_facts`, `issues_facts`, and `sourcecraft_issues`; events
and comments can be supplied as row-level events or through the corresponding
top-level SourceCraft-derived collections.  Aggregate rows such as
`issues_first_time_opened` are not expanded into invented issue instances.

The implementation lives in:

- `packages/core/src/repowise/core/analysis/health/integrations/issues_facts.py` — policy loading, actor classification, source normalization, deduplication, redacted immutable facts;
- `packages/core/src/repowise/core/analysis/health/integrations/issues_analyzer.py` — pure metrics, evidence, status mapping, and local score;
- `packages/core/src/repowise/core/analysis/health/integrations/chaoss_adapter.py` — the single routing boundary that preserves the legacy result and invokes `IssuesAnalyzer`;
- `config/analyzers/issues.yaml` — versioned policy and thresholds;
- `scripts/verify_issues_fixture.py` — redacted SourceCraft-path verification.

The analyzer version is `issues-sourcecraft-policy-v1`.  The version and the
policy digest are included in provenance and cache identity.  Changing the
policy file therefore cannot reuse a result calculated with the old policy.

## Normalized facts

`IssueFact` contains only normalized scalar lifecycle data:

- stable issue id, optional number and URL;
- created/updated/closed timestamps normalized to UTC;
- `OPEN`, `CLOSED`, or `UNKNOWN` state;
- redacted `author_key` and actor class;
- immutable `IssueEventFact` tuples;
- pull-request marker and per-field coverage;
- source reference and malformed-record flag.

`IssueEventFact` contains a stable event id, issue id, event type, UTC
timestamp, redacted actor key, actor class, classification reason, and whether
the event is an explicit state transition.  Comment bodies, raw actor logins,
emails, and complete source payloads are not stored in facts or emitted in
evidence.

`IssueCollectionFacts` additionally records source status, observed/expected
records, pagination and date-filter state, comment/state-event availability,
actor coverage, permission state, malformed and duplicate counts, coverage,
confidence, limitations, and a bounded diagnostic summary.

Issue and event deduplication uses stable source ids only.  Duplicate issue
rows do not increase denominators; duplicate event ids are ignored within an
issue.  Records identified as pull requests are excluded before all Issues
denominators are formed.  Rows are never merged by title, URL similarity, or
timestamp alone.

## Policy and windows

All windows use the context `as_of_ts` in UTC, not wall-clock time during the
calculation:

| Policy | Value | Purpose |
| --- | ---: | --- |
| analysis window | 90 days | issue cohort and trend population |
| trend bucket | 30 days | three deterministic buckets inside the analysis window |
| maturity window | 30 days | close-time and closure-ratio cohort |
| stale threshold | 30 days | old open issue with no qualifying activity |
| old backlog threshold | 90 days | age signal and backlog evidence |
| minimum sample | 5 | minimum denominator for strong components |
| minimum coverage | 0.80 | minimum source confidence/coverage for strong components |

There is no arbitrary 15-day duration fallback.  An unanswered issue remains
unanswered and has no response duration.  An open issue has no close duration.
An issue created outside the analysis window is not part of the response cohort,
but an open issue in the current snapshot can still contribute to backlog age.

## Actor and bot policy

Classification precedence is:

1. explicit source bot/human marker;
2. source account type;
3. configured known bot identity;
4. configured anchored bot pattern;
5. an explicit actor mapping is human when it is not otherwise identified as a bot;
6. unknown when no reliable actor identity exists.

The current configured bot identities/patterns cover Dependabot, Renovate, and
GitHub Actions naming.  Patterns are repository-owned in
`config/analyzers/issues.yaml` and are matched as full identities.

Bot comments count as comment activity but never qualify as a first human
response.  The issue author is excluded from first-response qualification by
policy.  Unknown actors are excluded from the human response numerator and
reduce actor coverage; they are not silently treated as human.

## Metrics

The analyzer emits `issues:*` observations with explicit population and
denominator values.  Values that cannot be measured are `null` and are
described by diagnostics/limitations rather than converted to zero.

- `open_issues` and `closed_issues` use the as-of state.
- `closure_ratio` is mature closed issues divided by mature issues.
- `first_human_response_count`, `unanswered_issues`, and
  `unanswered_ratio` use the analysis cohort.  The first qualifying human
  comment determines response time.
- `first_response_median_hours` and `first_response_p75_hours` use sorted
  measured response durations and deterministic linear interpolation.
- If comments are unavailable or incomplete, response count, unanswered count,
  response ratios, and response percentiles are `null`; the analyzer does not
  reinterpret missing comments as unanswered issues or emit response findings.
- `time_to_close_median_hours` and `time_to_close_p75_hours` use valid close
  durations for mature closed issues only.  A reopened issue is considered
  open or closed according to the latest explicit transition; its close time
  uses the latest valid close event when it is closed at the snapshot.
- `stale_open_issues` requires an open issue older than the stale threshold and
  no qualifying human comment or explicit reopen in the stale window.
- If the comment collection is unavailable, stale classification for open
  issues is also unavailable and the backlog component is omitted rather than
  treating missing activity as proof of staleness.
- `open_age_median_hours`, `open_age_p75_hours`, `oldest_open_age_hours`,
  `old_open_issues`, and configured non-overlapping age buckets describe the
  current open backlog.
- `reopened_issues` and `reopen_ratio` are measured only when explicit state
  events are available.  Missing transitions are `NOT_APPLICABLE`, not zero.
- `comments_human`, `comments_bot`, and `comments_unknown` expose activity
  without allowing bot activity to improve responsiveness.
- `issues:trend:*` contains created, closed, net, human-comment, bot-comment,
  unknown-comment, and explicit-reopen counts for each 30-day bucket.
- `sample_size` is the number of issues in the response cohort.

## Coverage and status

`IssueMetricStatus` is deliberately more specific than the shared
`AnalyzerStatus`:

| Facts status | Meaning | Result behavior |
| --- | --- | --- |
| `MEASURED` | granular issue source was usable | metrics are measured; score is possible only after sample/coverage gates |
| `NO_ISSUES` | complete issue source returned no issues | counts can be zero; no health bonus and no Issues-only score |
| `PARTIAL` | usable facts with incomplete pagination, filtering, or malformed rows | metrics are bounded; affected components are omitted; result is `WARN` |
| `UNAVAILABLE` | collector did not supply granular data or permission was absent | no synthetic issue metrics; `SKIPPED` when no legacy PR envelope exists, otherwise legacy result is preserved |
| `ERROR` | normalization/policy/source failure | `ERROR` without a usable base, otherwise `WARN` with the base result preserved |
| `NOT_APPLICABLE` | a specific metric cannot be defined, for example reopen without state events | diagnostic/limitation state only; not a shared analyzer status |

The surrounding legacy PR result has its own status.  A PR-only fixture can
remain `PASS` with its `chaoss:pull_requests_new` metric while the issue
sub-status is `NO_ISSUES`.  This prevents issue completeness from being
confused with PR availability.

## Issues score

The global Score Engine is unchanged.  Issues owns a local score made from
four explanatory components:

```text
responsiveness    = answered_ratio * response_latency_quality * 100
resolution        = closure_ratio * close_latency_quality * 100
backlog_health    = 50 when a measured mature backlog is empty,
                    otherwise 100 * (0.60 * (1 - stale_ratio)
                                     + 0.40 * age_quality)
maintenance_trend = closed_in_trend / (created_in_trend + closed_in_trend) * 100
```

Response and close latency quality each average median and P75 threshold
signals.  A measured reopen ratio applies a bounded resolution penalty.  The
four configured weights are `0.30`, `0.30`, `0.25`, and `0.15`.  Components
below the sample/coverage gate are omitted from the local weighted denominator;
at least two eligible components including resolution or backlog are required.

Complete absence of issues never produces a healthy Issues score.  One issue
can produce facts/evidence, but cannot satisfy the minimum sample gate.  A
missing collector cannot produce a zero score.

The result exposes one aggregate `AnalyzerResult.score` with canonical
`score_dimension="delivery"`.  Every explanatory `MetricValue` has
`score=None`.  This is intentional: the unchanged compositor consumes the
aggregate once and cannot average the four components a second time.  If a
legacy Issues/PR base score exists, the new Issues score has a maximum share
of `0.25`:

```text
final = base * 0.75 + issues_quality * 0.25
```

If no base score exists, the measured Issues quality is the single aggregate
score.  The local diagnostics include component scores, omitted components,
sample sizes, coverage, applied share, and a double-count guard.

## Evidence and privacy

Bad signals retain bounded evidence containing the issue id in the stable
subject, issue URL when supplied, age/response/close reason, and a redacted
SourceCraft JSON pointer.  Findings are capped by policy.  No comment body,
raw actor login, email, diff, or complete API response is stored.  Evidence
confidence is derived from collection confidence and issue field coverage.

## Tests and verification

Focused tests:

```text
uv run pytest -q tests/unit/health/test_issues_facts.py
uv run pytest -q tests/unit/health/test_issues_analyzer.py
uv run pytest -q tests/integration/test_issues_analyzer.py
```

The deterministic fixtures cover empty and single-issue populations, human and
bot response order, stale/open/closed issues, explicit reopen events,
percentiles, trends, duplicate and pull-request rows, malformed records,
partial comments, unavailable granular inventory, legacy PR envelopes, cache
identity, deterministic ordering, and unchanged global composition.

Live verification uses only the existing collector boundary:

```text
uv run python scripts/verify_issues_fixture.py
```

An exported collector inventory can be supplied explicitly:

```text
uv run python scripts/verify_issues_fixture.py --inventory path/to/sourcecraft-inventory.json
```

The report is written to
`spikes/issues/runs/repo-health-issues.json`.  On the current local fixture
`artem03102006/codex-external-audit-public-20260916`, no granular SourceCraft
issues/comments export is present, so the honest live state is
`UNAVAILABLE`, with no score delta.  Rich lifecycle behavior is demonstrated
only by local deterministic tests and is not presented as live data.

## Rollback

Rollback is one boundary change in `chaoss_adapter.py`: route
`issues_prs_adapter()` back to `ChaossAdapter.result()` while retaining the
policy/facts modules for later re-enable.  No data migration, external service
rollback, Vale/PyDriller change, or global Score Engine change is required.
