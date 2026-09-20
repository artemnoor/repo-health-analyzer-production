# Activity Analyzer: PyDriller integration

This document describes the optional Git-history source used by the existing
`chaoss.activity` analyzer. The integration is pinned to PyDriller 2.12 and the
audited upstream revision `a527c83ba81ee949cb84b977c155f337423743be`.

## Boundary

The dependency is an in-process Python library. The production path does not
invoke a PyDriller CLI, construct subprocess commands, or expose PyDriller
objects outside the adapter:

```text
SourceCraft/Git collector
        |
        v
AnalyzerContext + existing chaoss.activity result
        |
        v
ActivityAnalyzer
        |
        v
PyDrillerAdapter -- PyDriller Repository API -- local Git repository
        |
        v
normalized PyDrillerFacts
        |
        v
one existing chaoss.activity AnalyzerResult
```

`ActivityAnalyzer` receives only `PyDrillerFacts`. It does not import
PyDriller `Repository`, `Commit`, or `ModifiedFile` classes and does not parse
library internals. The adapter reads scalar commit metadata and modification
counters, then immediately releases the library objects. Full messages,
patches, source contents, and raw emails are not retained.

## Files and ownership

- `packages/core/src/repowise/core/analysis/health/integrations/pydriller_adapter.py`
  owns dependency loading, Git reference resolution, traversal, aggregation,
  failure mapping, and normalized facts.
- `packages/core/src/repowise/core/analysis/health/integrations/activity_analyzer.py`
  owns composition, observable Activity metrics, and the bounded quality
  score.
- `config/analyzers/pydriller.yaml` is the versioned policy. Changes to the
  policy revision or Activity analyzer version invalidate cached results.
- `scripts/verify_pydriller_activity_fixture.py` produces the redacted live
  report at `spikes/activity/pydriller/runs/repo-health-activity.json`.

SourceCraft remains authoritative for MR/PR events, releases, platform
metadata, and any activity not present in local Git. PyDriller does not infer
MRs, PRs, reviews, or releases from branch names or commit history.

## Normalized facts

`PyDrillerFacts` is immutable and library-independent. Its main groups are:

- provenance: tool version, upstream revision, policy revision/digest, duration,
  selected/excluded refs, and repository head;
- source state: `MEASURED`, `NO_ACTIVITY`, `UNAVAILABLE`, or `ERROR`;
- history: occurrence count, unique commit count, duplicate count, bounded
  hash sample, author/committer timestamps, and recent commit summaries;
- people: unique authors/committers and bounded identity-key aggregates. Raw
  email addresses are never exposed;
- changes: modified-file records, bounded file history, additions, deletions,
  churn, merge commits, empty commits, low-change commits, and change types;
- dynamics: 7/30/90/365-day windows, fixed buckets, active periods,
  meaningful-activity ratio, latest-activity age, and inactivity gaps;
- completeness: shallow-history state, truncation state, coverage, confidence,
  and optional exact overlap with an existing Git baseline.

The adapter uses bounded structures for recent commits, file histories,
contributors, and exact hash deduplication. When a configured safety bound is
reached, the result is marked truncated and its coverage/confidence is capped.

## Reference policy

The default is `default_branch`:

- the collector-provided/default local branch is selected, falling back to the
  checked-out local head or a deterministic local head;
- remote refs, PR-like branches, and tags are excluded;
- merge and empty commits are included;
- traversal order is `date-order`;
- all occurrences are deduplicated by the full commit hash before any aggregate
  is updated.

Two explicit audit scopes are available through
`context.inventory["pydriller_scope"]`:

- `all_local_refs` includes local branches;
- `all_refs_with_remotes` additionally includes remote-tracking refs, but not
  tags unless a future policy explicitly enables them.

The all-ref scopes are audit modes, not the production default. A commit
reachable from several refs may increase `commit_occurrence_count`, but it can
increase neither `unique_commit_count`, churn, contributor counts, nor the
quality score more than once.

## Activity metrics and score

The existing Activity result keeps its existing SourceCraft/CollectOSS rows.
PyDriller adds prefixed, non-scored observations such as:

- `pydriller:unique_commits`, `pydriller:commits_7d/30d/90d/365d`;
- `pydriller:unique_authors`, `pydriller:unique_committers`;
- additions, deletions, churn, merge/empty/low-change counts;
- latest-activity age and current/longest inactivity;
- active periods, meaningful-activity ratio, file-history coverage, coverage,
  and confidence.

When history is measured, exactly one PyDriller metric is scored:
`pydriller:activity_quality`, dimension `history`, denominator `1`. Its
bounded 0--100 value is configured as:

```text
0.55 * recency_signal
+ 0.30 * regularity_signal
+ 0.15 * meaningful_activity_signal
```

Recency is a half-life decay from the latest committer activity. Regularity is
based on active fixed buckets over the observed history span. Meaningful
activity discounts empty and low-change commits, but its contribution is only
15%. Raw commit count, churn, contributor count, merge count, and warning
volume are evidence—not direct linear score penalties.

If the existing Activity result already has a numeric score, PyDriller's share
is capped at `pydriller_max_share: 0.25` inside `ActivityAnalyzer`. If there is
an existing score, the result carries the capped blend and the quality row is
kept as a non-scored observation; emitting a second scored row would make the
unchanged composite engine average the uncapped PyDriller value. If there is no
existing score, the measured PyDriller quality metric supplies the single
Activity score. The global Score Engine and its dimension weights are unchanged.

## Status and coverage mapping

| Facts state | Meaning | Activity result without another usable source | Score |
| --- | --- | --- | --- |
| `MEASURED` | Valid history was traversed and at least one commit was aggregated | `PASS`, or `WARN` for shallow/truncated history | bounded quality metric may be present |
| `NO_ACTIVITY` | Valid repository and selected scope contain no commits | `INCONCLUSIVE` with `insufficient_denominator` | absent, never zero |
| `UNAVAILABLE` | PyDriller, Git capability, or repository path is unavailable | `SKIPPED` with `missing_capability` | absent; existing source score is preserved |
| `ERROR` | Invalid repository, policy/ref error, traversal failure, or timeout | `ERROR`, or `WARN`/preserved base status if another source is usable | absent; never zero |

Shallow history is still measured when traversal can proceed. It is marked
incomplete, receives a lower confidence/coverage cap, and gets an explicit
limitation. A shallow boundary whose parent diff is unavailable is counted as
history with incomplete file/churn facts rather than being mislabeled as an
empty commit.

When an existing Git baseline supplies exact commit hashes, diagnostics expose
`overlap_commit_count`, `new_commit_count`, and `overlap_status=measured`.
Without hashes the status is `unknown`; zero is never used as a substitute for
an unmeasured overlap. The `double_count_guard` explicitly states that
PyDriller counts are not added to existing Git/source counts.

## Verification

Focused tests:

```text
uv run pytest -q tests/unit/health/test_pydriller_adapter.py
uv run pytest -q tests/unit/health/test_activity_analyzer_pydriller.py
uv run pytest -q tests/integration/test_pydriller_activity.py tests/integration/test_pydriller_smoke.py
```

Live verification:

```text
uv run python scripts/verify_pydriller_activity_fixture.py
```

The fixture is `artem03102006/codex-external-audit-public-20260916`. The
redacted report records both the production default-branch run and a separately
labeled all-ref audit. The observed cross-check is 7 unique commits and churn
234 on `main`, versus 13 unique commits, 59 traversal occurrences, 46 duplicate
occurrences, 3 authors, and churn 273 across local/remote refs. These values
are recorded from the run; they are not hard-coded into the adapter.
