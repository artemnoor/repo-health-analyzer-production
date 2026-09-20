# CI/CD Analyzer

`cicd.sourcecraft` is the repository-owned CI/CD analyzer. It uses the
existing SourceCraft CI collector as its only runtime data source. Apache
DevLake is not started, embedded, or called at runtime; its data model and DORA
definitions are methodology references only.

## Boundary

The health edge supplies a versioned `sourcecraft_cicd` envelope. The analyzer
does not make HTTP requests, read `SOURCECRAFT_PAT`, invoke a CLI, or expose
SourceCraft response objects. `SourceCraftCICDAdapter` validates and converts
that envelope into immutable `CICDFacts`; `CICDAnalyzer` consumes only those
facts and returns the normal `AnalyzerResult` contract.

The canonical envelope is `sourcecraft-cicd-inventory-v1`. Compatibility input
aliases `cicd_runs` and `sourcecraft_cicd_runs` are accepted during migration.
Runs are deduplicated by stable run id. A duplicate winner is selected
deterministically using completeness, `updated_at`, then a canonical payload
digest. The analyzer never double-counts the same run received through several
pages.

## Windows and metrics

The checked-in policy is [config/analyzers/cicd.yaml](../../config/analyzers/cicd.yaml):

- 90-day analysis horizon;
- current, previous, and oldest half-open 30-day windows;
- pagination and date filtering are performed by the collector locally because
  the SourceCraft endpoint has no server-side date filter;
- P50 and P95 use deterministic linear interpolation;
- SUCCESS and FAILURE are decisive; CANCELLED, SKIPPED, and REJECTED remain
  visible but do not become failures;
- IN_PROGRESS and UNKNOWN are excluded from terminal rates;
- retry/flaky is reported only when an explicit retry/correlation/parent
  relation is present and workflow/commit identity does not contradict it.

The result exposes total, terminal, decisive, status counts, success/failure
rates, last observed and successful run timestamps, failure streak, duration
P50/P95, current-versus-previous deltas, trend, sample sizes, pagination
coverage, and confidence. Evidence points to SourceCraft JSON pointers and run
ids/deep links when supplied; logs, secrets, and comment-like payloads are not
retained.

## Status semantics

| Facts status | Meaning | Analyzer result |
| --- | --- | --- |
| `CI_NOT_CONFIGURED` | SourceCraft explicitly says CI is not configured | `skipped`, score `null` |
| `NO_RUNS` | CI is configured and pagination is complete, but no run exists | `inconclusive`, score `null` |
| `INSUFFICIENT_HISTORY` | History exists but does not meet the minimum sample | `inconclusive`, score `null` |
| `PARTIAL` | A page/token or required field was incomplete | `warn` when scoreable, confidence reduced |
| `UNAVAILABLE` | Source/API/capability data is unavailable | `skipped`, score `null` |
| `ERROR` | Malformed schema or analyzer/policy failure | `error`, score `null` |
| `MEASURED` | Required history and fields are sufficient | measured score/status |

Absence of CI or inability to fetch it is never converted into a zero score.
One successful run is visible as a metric but cannot produce a score.

## Score policy

The local delivery score has four independently eligible components:

`reliability` (40%) combines decisive success rate with completion health;
`failure_streak` (25%) combines failure rate and the current consecutive
failure streak; `duration` (20%) evaluates P50/P95 against the configured target
and breach thresholds; and `trend` (15%) evaluates failure-rate and duration
change between current and previous windows. Components require their own
minimum samples. The weighted score is multiplied by facts confidence and
bounded to `0..100`; if fewer than two components are eligible, score is
`null`. This score is local to the CI/CD category and does not alter the global
Score Engine.

## DORA applicability

Deployment Frequency, Lead Time for Changes, Change Failure Rate, and Time to
Restore are not inferred from ordinary CI runs. They are `NOT_APPLICABLE` until
the SourceCraft inventory contains real deployment/environment/incident facts
needed by the corresponding definition. No synthetic deployment or incident is
created from a successful build.

## Verification

```bash
uv run pytest -q tests/unit/health/test_cicd_facts.py tests/unit/health/test_cicd_analyzer.py tests/integration/test_cicd_analyzer.py tests/integration/test_integration_cicd_cache.py
uv run python scripts/verify_cicd_fixture.py --inventory tests/fixtures/cicd/all_success.json
SOURCECRAFT_PAT=... uv run python scripts/verify_cicd_fixture.py --live
```

The live artifact is written to
`spikes/cicd/runs/sourcecraft-live-cicd.json`. It records run counts, statuses,
rates, durations, trend, score, status, coverage, confidence, evidence
references, and any fetch limitation. If the PAT is absent or the endpoint is
unavailable, the report preserves that state instead of claiming a zero score.
