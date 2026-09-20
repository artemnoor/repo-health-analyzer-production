# Code Health Analyzer

Code Health is an enrichment of the existing `repowise.health` analyzer. It
does not register a second analyzer and does not change the global Score
Engine. The legacy RepoWise findings and file metrics remain available; when
the optional engines produce a usable result, their one aggregate score is
the category score and component rows are observation-only.

## Data flow

```text
local checkout -> official SonarScanner -> SonarQube Web API -> SonarQubeAdapter
local Git repo -> official git-sizer JSON v2 -> GitSizerAdapter
Git/history inventory --------------------------------------> TodoDebtAdapter
                                      \                    /
                                       -> CodeHealthFacts -> CodeHealthAnalyzer
                                                               -> repowise.health
```

`CodeHealthAnalyzer` receives only normalized `CodeHealthFacts`. It never
starts a process, calls Web API, parses SonarQube JSON, or sees git-sizer
objects. The collector/adapters enforce output and evidence limits.

## Sources and boundaries

The checked-in policy is [`config/analyzers/code-health.yaml`](../../config/analyzers/code-health.yaml).
It fixes the policy revision, exclusion patterns, component weights, old TODO
threshold, evidence caps, and Sonar metric aliases. Production deployments
use an official SonarQube Community Build server and scanner; SonarQube source
is not embedded in this repository. git-sizer is an official CLI dependency
and its JSON v2 boundary is normalized without retaining full output.

SonarQube is used only for Code Health signals: maintainability rating, smells,
technical debt/remediation, complexity, duplication, LOC, reliability bugs,
components, and issues. Vulnerabilities and security hotspots are ignored here;
SourceCraft AppSec remains the Security source. Coverage is `NOT_APPLICABLE`
unless a real coverage report provenance is supplied to the Sonar snapshot.

The canonical inventory keys are:

- `sonarqube_code_health`: a redacted snapshot, or `code_health_enabled` plus
  `sonarqube_project_key` and an injected Web API transport;
- `git_sizer`: an optional redacted JSON v2 snapshot;
- `git_history_code_health`: normalized TODO/FIXME, age/blame, and hotspot facts;
- `code_health_source_map`: optional source text map used only at the local
  collection edge and never retained in `CodeHealthFacts`.

When `RepoWiseAdapter` is the caller, it passes its already-built `git_meta_map`
to the Code Health composition context. `TodoDebtAdapter` reuses the attached
FULL-tier `BlameIndex`, `is_hotspot`, and churn metadata from that map, so TODO
age/hotspot evidence does not trigger a second Git history or blame walk.

`RepoWiseAdapter` activates this enrichment only when one of these keys is
present or `code_health_enabled: true`. With no Code Health inventory, the
existing baseline behavior is unchanged.

## Normalized facts

`CodeHealthFacts` contains bounded `SonarFacts`, `GitStructureFacts`, and
`TodoDebtFacts`, plus per-engine status/coverage, policy digest, exclusions,
baseline summary, and a source snapshot digest. Public engine states are:

- `MEASURED`: complete usable facts;
- `PARTIAL`: usable facts with incomplete pages/history/blame;
- `UNAVAILABLE`: tool, server, API, or source capability is absent;
- `ERROR`: malformed or failed source boundary;
- `NOT_APPLICABLE`: the concept has no valid population, such as missing
  coverage provenance.

Missing data is never converted to a zero quality score. If the optional
engines are unavailable but the existing baseline is measured, that baseline
score is preserved and diagnostics identify the unavailable engine. If there is
no baseline and no usable engine, the result has no score.

## Local score

The local Code Health score uses the following bounded components:

| Component | Weight | Signal |
| --- | ---: | --- |
| maintainability/debt | 0.35 | rating, debt density, smells |
| complexity | 0.15 | cognitive/cyclomatic complexity normalized by LOC |
| duplication | 0.15 | duplicated-line density, count fallback |
| hotspots/churn | 0.15 | normalized existing history hotspots |
| TODO/FIXME debt | 0.10 | marker density and old-marker ratio |
| Git structure | 0.10 | git-sizer concern, blob, depth, checkout signals |

Ineligible components are removed and eligible weights are renormalized. The
result is then adjusted by facts confidence. A partial result is capped by the
versioned partial-score cap. Raw finding counts are not subtracted directly,
so one old TODO, one large blob, or one Sonar warning cannot reduce the score
to zero. The old per-file metrics have `score=None` only for an enriched run;
this prevents the shared composer from counting both file metrics and the new
aggregate. The global composer and its weights are unchanged.

## Evidence and redaction

Evidence contains only safe identifiers and locations: Sonar issue/rule ID,
component/path/line, severity and effort; git-sizer metric/object path and JSON
pointer; TODO path/line/marker/age and abbreviated blame commit. Full source,
comments, diffs, scanner logs, secrets, and Sonar Security payloads are not
stored.

## Verification

The focused deterministic tests are:

```powershell
& .venv\Scripts\python.exe -m pytest -q tests/unit/health/test_code_health.py
```

The live harness performs scanner -> Compute Engine -> Web API -> normalized
facts -> analyzer verification. It uses `SONARQUBE_TOKEN` without writing it:

```powershell
& .venv\Scripts\python.exe scripts/verify_code_health_fixture.py
```

The harness prefers a temporary official `sonarqube:community` container,
falls back to `SONARQUBE_HOME`, and can target an existing server with
`--sonar-url`/`--skip-scan`. The redacted output contains real measures,
git-sizer metrics, TODO facts, baseline/after score, status, coverage,
confidence, and evidence references. By default it writes
`spikes/code_health/runs/sourcecraft-live-code-health.json`.

The live artifact is safe to commit or attach for review: it identifies the
fixture by repository, HEAD SHA, and analysis timestamp, but does not include
the local checkout path, token, scanner logs, source text, or full SonarQube
responses. It also records the Compute Engine terminal status, API page
completeness, Docker/standalone startup outcome, and a bounded projection of
the real Sonar, git-sizer, and TODO evidence. A failed operational run is
reported through structured `[FIX:live-report]` logs without logging secrets.
