# External Providers Production Readiness

## Verdict

**PRODUCTION PIPELINE READY: YES**

**READINESS VERDICT: PASS**

Sanitized machine-readable live evidence is stored in
[external-providers-live-evidence.json](external-providers-live-evidence.json).

The canonical production composition now wires the real SourceCraft Issues and
CI/CD providers, the existing AppSec chain, PyDriller, Vale, git-sizer,
TODO-history, and SonarQube through one runtime builder. API and worker modes
execute the same collector and analyzer graph. Frozen Score Engine v1,
calibration-v2, weights, security caps, coverage thresholds, confidence
formulas, and analyzer formulas were not changed.

The live proof below uses a controlled SourceCraft fixture and a local native
SonarQube instance. Docker Desktop was not used because its Linux daemon was
unavailable in this environment; this is documented as an environment
limitation, not hidden by a fallback.

## Production path

```text
AnalysisRequest
  -> build_production_runtime()
  -> shared SourceCraftClient / local tool adapters
  -> CollectionService
  -> RepositoryFacts
  -> six canonical analyzers
  -> unchanged ScoreEngineV1
  -> persistence / API or worker result
```

The SourceCraft client follows the official paginated REST envelopes, applies
bounded page and row limits, maps authentication/status/timeout failures, and
never stores raw payloads or credentials. SourceCraft Issues and CI/CD use the
official repository-scoped paths; AppSec remains a separate scans →
defect-groups → findings chain.

## Live provider matrix

| Category | Provider | Live verified | Coverage | Remaining limitation |
| --- | --- | --- | --- | --- |
| Documentation | Vale adapter through production composition | Adapter wiring and unavailable behavior verified; Vale binary was unavailable | `unavailable`, confidence `0.0` in the six-category run | Install/configure Vale to produce real findings |
| Activity | PyDriller 2.12 + Git | YES; real checkout traversed through production runtime | `complete`, confidence `1.0`; score `15.5500` on the controlled small checkout | The fixture is intentionally small and old; this is an observation, not recalibration |
| Issues | SourceCraft Issues REST: `/repos/{org_slug}/{repo_slug}/issues` plus bounded comments | YES; 8 real issues, 5 open, 3 closed, 5 answered | `complete`, confidence `1.0` on the issues fixture; empty history stays inconclusive | The combined CI fixture has no issues, so no Issues score is fabricated |
| CI/CD | SourceCraft CI REST: `/repos/{org_slug}/{repo_slug}/cicd/runs` | YES; 10 real runs, 7 success, 3 failed | `complete`, confidence `1.0`; score `76.3158`; trend components remain partial | Controlled fixture does not provide every optional trend component |
| Security | SourceCraft AppSec: `/v1/scans` → `/v1/defect-groups` → `/v1/findings` | Adapter path and safe unavailable behavior verified; controlled fixture returned no scans | `unavailable`, confidence `0.0`; no fabricated security score | Use a controlled SourceCraft AppSec fixture with safe synthetic findings for a positive live proof |
| Code Health | SonarScanner 8.1 → SonarQube 26.9 REST, plus Git/TODO and git-sizer adapter | YES for SonarQube; scanner quality gate passed and REST measures reached the collector | `partial`, confidence `0.65`; score `100.0` on the tiny fixture | git-sizer was unavailable; Sonar-backed score remains a current-engine observation |

The Code Health score of `100.0` on the tiny controlled fixture is preserved as
observed behavior. It was not adjusted during this readiness work. The fixture
is not a calibration corpus and must not be used to tune formulas.

Docker recovery and the reproducible official-image path are documented in
[docker-sonarqube-setup.md](docker-sonarqube-setup.md).

## Six-category production E2E

Controlled checkout: `D:\RepoHealthCalibration\probe\template-python`, branch
`master`. SourceCraft identity:
`artem03102006/repo-health-calibration-ci-mixed`. Sonar project key:
`artem03102006.repo-health-calibration-ci-mixed`.

The scanner completed successfully and the SonarQube quality gate was green.
The same request was then executed using both production modes:

| Mode | Analysis state | Overall score | Result |
| --- | --- | ---: | --- |
| API/local executor | `partial` | `null` / `INSUFFICIENT_DATA` | PASS: unavailable categories remained explicit |
| Worker executor | `partial` | `null` / `INSUFFICIENT_DATA` | PASS: projection matched API mode |

The overall score is intentionally absent because the fixture did not provide
enough scored categories after Documentation, Issues, and Security degraded
honestly. No unavailable category was converted into zero.

A second live production-runtime smoke used the controlled Issues fixture
(`artem03102006/repo-health-calibration-issues`). It produced an Issues
`warn` result with score `68.3442`, complete coverage, high confidence, and
one normalized evidence group. The same run correctly kept CI/CD inconclusive
for that repository, AppSec unavailable, and the optional local tools partial
or unavailable; this confirms that a real Issues result does not require
substituting GitHub data or fabricating the other categories.

Measured on the local Windows environment (one small checkout; wall-clock
timings, not performance targets): SonarScanner analysis `11.448 s`, API/local
production execution `1.907 s`, worker production execution `1.608 s`.

The repeatable timed run also captured the individual phases:

| Phase/source | Time |
| --- | ---: |
| Controlled clone | `180 ms` |
| SonarScanner | `10,996 ms` |
| Git | `58 ms` |
| git-sizer (unavailable startup) | `11 ms` |
| Git/TODO history | `11 ms` |
| PyDriller | `346 ms` |
| SonarQube REST | `294 ms` |
| SourceCraft AppSec | `347 ms` |
| SourceCraft CI/CD | `411 ms` |
| SourceCraft Issues | `346 ms` |
| Vale (unavailable startup) | `6 ms` |
| Normalization | `8 ms` |
| Analyzer execution | `5 ms` |
| Score engine | `<1 ms` |
| Total production analysis | `1,855 ms` |

Observed category projection in both modes:

| Analyzer | Status | Score | Coverage | Confidence | Evidence |
| --- | --- | ---: | --- | ---: | ---: |
| Activity | `fail` | `15.5500` | complete | 1.00 | 1 |
| CI/CD | `warn` | `76.3158` | complete | 1.00 | 1 |
| Code Health | `warn` | `100.0` | partial | 0.65 | 1 |
| Documentation | `skipped` | N/A | unavailable | 0.00 | 0 |
| Issues | `inconclusive` | N/A | partial | 0.00 | 1 |
| Security | `skipped` | N/A | unavailable | 0.00 | 0 |

API and worker category projections, statuses, source capabilities, and
limitations were identical.

## Direct SourceCraft evidence

The controlled Issues fixture returned the official envelope and normalized:

- `issue_count=8`, `open_count=5`, `closed_count=3`;
- `open_age_p75_hours≈36.1142`, `stale_count=0`, `stale_ratio=0.0` at the
  recorded validation time;
- `answered_count=5`, `comments_available=true`;
- `coverage=1.0`, `confidence=1.0`;
- bounded comment enrichment completed for all eight issues.

The controlled CI fixture returned:

- `run_count=10`, `success_count=7`, `failed_count=3`;
- `failure_rate=0.3`;
- `success_rate=0.7`, with the latest status preserved as `last_run_status`;
- `p50_seconds≈3.4812`, `p95_seconds≈4.3534`;
- `coverage=1.0`, `confidence=1.0`.

These values came from SourceCraft REST, not GitHub Issues or GitHub Actions.

## SonarQube evidence

- Native SonarQube status endpoint: HTTP 200 / `UP`.
- Official SonarScanner archive: 8.1.0.6389.
- Scanner execution: PASS.
- Quality gate: PASS.
- Collector returned numeric Sonar measures and normalized
  `sqale_rating=1` to the existing contract's `maintainability_rating=A`.
- No analyzer or Score Engine formula was changed.
- A temporary local scanner token was revoked after the live run.

The obsolete `maintainability_rating` REST metric key was removed from the
adapter request because SonarQube 26.9 rejects that key. The canonical
`sqale_rating` value is normalized at the adapter boundary; this preserves the
existing analyzer contract and scoring semantics.

## Docker environment limitation

Docker Desktop was inspected without resetting data or deleting volumes. The
selected `desktop-linux` context could not connect because the
`dockerDesktopLinuxEngine` pipe was missing. Docker logs reported:
`dockerd failed to start: starting rpcbind: signal: killed`; the Desktop error
also reported `com.docker.build` exit status 1. Low free space was observed on
the system volumes.

The live proof therefore used native SonarQube and the official local scanner.
The application itself correctly exposes capability states and does not assume
Docker availability.

## Tests added and preserved

Targeted provider/composition tests cover:

- official Issues pagination and comment normalization;
- official CI terminal status and duration normalization;
- repeated/malformed page-token rejection;
- empty Issues history remaining inconclusive;
- `SOURCECRAFT_PAT` compatibility without serialization;
- automatic API/worker composition parity;
- unavailable Vale/git-sizer/Sonar behavior;
- existing AppSec three-stage isolation;
- token redaction and failure isolation.

Existing golden/parity tests remain the source of truth. No legacy Repowise
surface was reintroduced to make this run pass.

## Official references

- [SourceCraft API reference](https://api.sourcecraft.tech/docs/index.html)
- [SourceCraft OpenAPI document](https://api.sourcecraft.tech/sourcecraft.swagger.json)
- [SourceCraft REST API authentication](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/operations/api-start)
- [SourceCraft `src api` reference](https://vibe.sourcecraft.dev/portal/docs/en/cli-ref/src-api)
- [SourceCraft CI/CD workflows](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/ci-cd-ref/workflows)
