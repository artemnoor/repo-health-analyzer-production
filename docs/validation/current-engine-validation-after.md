# Current Repo Health Engine Validation

> Historical GitHub-only validation snapshot. Issues and CI/CD were intentionally
> not exercised through GitHub APIs. Current production SourceCraft provider
> wiring and live evidence are documented in
> [external-providers-readiness.md](external-providers-readiness.md).

This report records observed behavior of the existing production engine. It is not a calibration change and does not treat any absolute score as ground truth.

Engine validation status: **FAIL — BUG**
Safe to proceed to Recommendation Engine: **NO**
Reason: Do not start Recommendation Engine: 1 actual bug classification(s); 2 calibration question(s); controlled SourceCraft Issues/CI/CD/AppSec coverage is absent.

## Methodology

Each public GitHub URL was cloned into an isolated ignored checkout and run through the canonical production composition root (with the narrow Vale JSON compatibility fix recorded below): Git/PyDriller/Vale/SonarQube/git-sizer/TODO collectors as available → normalized RepositoryFacts → six analyzers → ScoreEngineV1. GitHub Issues, GitHub Actions, CodeQL, Dependabot, and other GitHub APIs were never used as SourceCraft substitutes.

Run as-of: `2026-09-21T12:00:00+00:00`; repositories attempted: `13`; artifacts: `artifacts/validation/20260921T-local-tools-full`

## Tool and environment evidence

| Engine | State | Reason |
| --- | --- | --- |
| git | available | executable available |
| git-sizer | available | executable available |
| git.todo-history | available | built-in bounded checkout scan |
| pydriller | available | package importable |
| sonarqube | unavailable | SONAR_URL is not configured |
| sourcecraft | unavailable | SOURCECRAFT_URL is not configured |
| vale | available | executable available |

Pinned tool manifest (URLs/SHA-256 only; no credentials):

```json
{
  "git-sizer": {
    "executable": "git-sizer.exe",
    "sha256": "52093c1cba0bb8e00da14c9eef678eb052fc729c32419415817076f06b5c85d8",
    "url": "https://github.com/github/git-sizer/releases/download/v1.5.0/git-sizer-1.5.0-windows-amd64.zip",
    "version": "1.5.0"
  },
  "sonar-scanner": {
    "executable": "sonar-scanner-8.1.0.6389-windows-x64\\bin\\sonar-scanner.bat",
    "sha256": "73f0e71928673d5b2f39bb86213342a30e51a14c8eec345164016bb29c8df8ee",
    "url": "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-8.1.0.6389-windows-x64.zip",
    "version": "8.1.0.6389"
  },
  "vale": {
    "executable": "vale.exe",
    "sha256": "7e55b39881f48ced8cf27406129c065a20247800e82e816a9e79d06c4b1a199e",
    "url": "https://github.com/vale-cli/vale/releases/download/v3.22.0/vale_3.22.0_Windows_64-bit.zip",
    "version": "3.22.0"
  }
}
```

Validation implementation notes:

- Vale adapter now parses the official file-keyed JSON shape and passes the validation config explicitly; scoring semantics are unchanged.
- Activity, Code Health, and Score Engine implementations were not modified by the validation run.

## Comparison table

| Repository | Type | Documentation | Activity | Code Health | Local Coverage | Overall state | Major observations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [andromeda](https://github.com/artemnoor/andromeda) | STRONG_USER | 80.00 | 90.69 | 16.19 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [CodeSlicer](https://github.com/Artem336600/CodeSlicer) | STRONG_USER | 80.00 | 53.02 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [fastapi](https://github.com/fastapi/fastapi) | GOLDEN_OSS | 80.00 | 87.45 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Freshly](https://github.com/Artem336600/Freshly) | WEAK | 80.00 | 25.00 | 80.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [MVP_FOOD](https://github.com/Artem336600/MVP_FOOD) | VERY_WEAK | 80.00 | 6.99 | 80.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Ocheredibm3](https://github.com/artemnoor/Ocheredibm3) | MIXED | 80.00 | 16.78 | 80.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | artifacts=1; cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Procsima-low_version-](https://github.com/artemnoor/Procsima-low_version-) | MIXED | 80.00 | 20.84 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | artifacts=3; cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [pydantic](https://github.com/pydantic/pydantic) | GOLDEN_OSS | 80.00 | 97.37 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [repo-health-analyzer-production](https://github.com/artemnoor/repo-health-analyzer-production) | STRONG_USER | 80.00 | 86.48 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [ruff](https://github.com/astral-sh/ruff) | GOLDEN_OSS | 80.00 | 99.90 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [TODO](https://github.com/Artem336600/TODO) | MIXED | 80.00 | 4.41 | 80.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating) | ADVERSARIAL | 80.00 | 14.54 | 80.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [uv](https://github.com/astral-sh/uv) | GOLDEN_OSS | 80.00 | 99.98 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | artifacts=5; cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |

## Before/after baseline comparison

Baseline: `artifacts/validation/20260921T193407Z-420d811d/summary.json`; baseline status: `PASS WITH COVERAGE LIMITATIONS (normalized from historical baseline label)`

| Repository | Same HEAD | Documentation before→after | Activity before→after | Code Health before→after | Before outcome | After outcome |
| --- | --- | --- | --- | --- | --- | --- |
| andromeda | YES | N/A → 80.00 (Δ N/A) | 90.72 → 90.69 (Δ -0.03) | N/A → 16.19 (Δ N/A) | degraded | degraded |
| codeslicer | YES | N/A → 80.00 (Δ N/A) | 53.02 → 53.02 (Δ -0.01) | N/A → 0.00 (Δ N/A) | degraded | degraded |
| fastapi | YES | N/A → 80.00 (Δ N/A) | 87.47 → 87.45 (Δ -0.02) | N/A → 0.00 (Δ N/A) | degraded | degraded |
| freshly | YES | N/A → 80.00 (Δ N/A) | 25.00 → 25.00 (Δ -0.00) | N/A → 80.00 (Δ N/A) | degraded | degraded |
| mvp-food | YES | N/A → 80.00 (Δ N/A) | 6.99 → 6.99 (Δ -0.00) | N/A → 80.00 (Δ N/A) | degraded | degraded |
| ocheredibm3 | YES | N/A → 80.00 (Δ N/A) | 16.78 → 16.78 (Δ -0.00) | N/A → 80.00 (Δ N/A) | degraded | degraded |
| procsima-low-version | YES | N/A → 80.00 (Δ N/A) | 20.84 → 20.84 (Δ -0.00) | N/A → 0.00 (Δ N/A) | degraded | degraded |
| pydantic | YES | N/A → 80.00 (Δ N/A) | 97.40 → 97.37 (Δ -0.03) | N/A → 0.00 (Δ N/A) | degraded | degraded |
| repo-health-analyzer-production | YES | N/A → 80.00 (Δ N/A) | 86.51 → 86.48 (Δ -0.03) | N/A → 0.00 (Δ N/A) | degraded | degraded |
| ruff | YES | N/A → 80.00 (Δ N/A) | 99.93 → 99.90 (Δ -0.03) | N/A → 0.00 (Δ N/A) | degraded | degraded |
| todo | YES | N/A → 80.00 (Δ N/A) | 4.41 → 4.41 (Δ -0.00) | N/A → 80.00 (Δ N/A) | degraded | degraded |
| two-cucumbersfloating | YES | N/A → 80.00 (Δ N/A) | 14.54 → 14.54 (Δ -0.00) | N/A → 80.00 (Δ N/A) | degraded | degraded |
| uv | NO | N/A → 80.00 (Δ N/A) | 99.83 → 99.98 (Δ 0.15) | N/A → 0.00 (Δ N/A) | degraded | degraded |

## Hypotheses

| ID | Status | Expected relationship | Classification | Evidence/cause |
| --- | --- | --- | --- | --- |
| H1 | PASS | MVP_FOOD should not outrank mature controls across categories | EXPECTED BEHAVIOR | available local category scores |
| H2 | PASS | Documentation should be noticeably higher than Activity | EXPECTED BEHAVIOR | TODO category scores |
| H3 | ANOMALY | Good documentation may coexist with limited substantive product | CALIBRATION QUESTION | validation-only inventory plus available category results |
| H4 | ANOMALY | Large mature repositories should not be systematically penalized only for size | CALIBRATION QUESTION | relative Code Health medians |
| H5 | PASS | Tiny repositories should not receive an unjustifiably high Code Health from absent complexity/duplication | EXPECTED BEHAVIOR | source inventory and Code Health |
| H6 | PASS | Unavailable GitHub-only SourceCraft metrics must not become numeric zero | EXPECTED BEHAVIOR | SourceCraft-only category projections |
| H7 | PASS | Coverage/confidence must show SourceCraft was not checked on GitHub | EXPECTED BEHAVIOR | SourceCraft-only category coverage/confidence |

## Anomalies and classifications

| Repository | Category | Class | Observed | Expected | Possible cause |
| --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A |

## Actual bugs

- `matrix`: Activity recency currently references wall-clock RepositoryFacts.collected_at instead of the fixed AnalysisRequest.as_of; do not auto-fix during validation.

## Calibration questions

- `H3`: validation-only inventory plus available category results
- `H4`: relative Code Health medians

## Expected behavior

None recorded.

## Limitations

- `matrix`: SONAR_URL is not configured
- `matrix`: controlled SourceCraft fixture is required

## Manual deep-dives

### mvp-food

Repository: [https://github.com/Artem336600/MVP_FOOD](https://github.com/Artem336600/MVP_FOOD)
Resolved HEAD: `27c20c152274f2a6f1421c1d45ec2105859d26bb`
Machine-readable artifact: `artifacts/validation/20260921T-local-tools-full/repositories/mvp-food.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 6.99 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 6.99; components=history=0.28, cadence=0.00, recency=0.00, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | warn | 80.00 | complete | high | 1 | code_health_score = (99.96*0.10) / 0.10 = 80.00 (active components only) |
| documentation | pass | 80.00 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 80.00; components=completeness=100.00, instructions=0.00, vale_quality=100.00, readability=100.00 |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

Raw normalized facts:

```json
{
  "capabilities": [],
  "cicd": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.cicd.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "code_health": {
    "available": true,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sonarqube.unavailable",
        "reason": "SONAR_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [
      {
        "evidence_ids": [],
        "key": "fixme_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "max_blob_size",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 409
      },
      {
        "evidence_ids": [],
        "key": "source_file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "todo_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "unique_blob_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "unique_commit_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "collected_at": "2026-09-21T20:31:17.006840Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "finding_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "git": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "author_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "authors_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "commits_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "head_sha",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "27c20c152274f2a6f1421c1d45ec2105859d26bb"
      },
      {
        "evidence_ids": [],
        "key": "history_complete",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "latest_activity_at",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "2025-03-18T13:23:42+00:00"
      },
      {
        "evidence_ids": [],
        "key": "ref",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "main"
      },
      {
        "evidence_ids": [],
        "key": "unique_commits",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "issues": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.issues.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "sonarqube.unavailable",
      "reason": "SONAR_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.appsec.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.cicd.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.issues.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    }
  ],
  "repository": {
    "canonical_uri": "https://github.com/Artem336600/MVP_FOOD",
    "head_sha": "27c20c152274f2a6f1421c1d45ec2105859d26bb",
    "provider": "github",
    "ref": "HEAD",
    "repository_id": "github.mvp-food",
    "schema_version": "repo-health.v1",
    "snapshot_id": null
  },
  "schema_version": "repo-health.v1",
  "security": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.appsec.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "source_snapshot_digest": null,
  "source_statuses": [
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git",
      "source_version": "git-cli",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git-sizer",
      "source_version": "json-v2",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git.todo-history",
      "source_version": null,
      "state": "partial"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "pydriller",
      "source_version": "2.12",
      "state": "available"
    },
    {
      "collected_at": "2026-09-21T20:31:18.731792Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sonarqube.unavailable",
          "reason": "SONAR_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sonarqube",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:18.731792Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.appsec.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.appsec",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:18.732794Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.cicd.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.cicd",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:18.732794Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.issues.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.issues",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "vale",
      "source_version": "vale-cli",
      "state": "available"
    }
  ],
  "source_versions": {
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "sourcecraft.cicd": "unavailable",
    "sourcecraft.issues": "unavailable",
    "vale": "vale-cli"
  }
}
```

### todo

Repository: [https://github.com/Artem336600/TODO](https://github.com/Artem336600/TODO)
Resolved HEAD: `c8ef35841cadd038d709087705e5c1ccd09e42e6`
Machine-readable artifact: `artifacts/validation/20260921T-local-tools-full/repositories/todo.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 4.41 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 4.41; components=history=0.18, cadence=0.00, recency=0.00, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | warn | 80.00 | complete | high | 1 | code_health_score = (89.85*0.10) / 0.10 = 80.00 (active components only) |
| documentation | pass | 80.00 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 80.00; components=completeness=100.00, instructions=0.00, vale_quality=100.00, readability=100.00 |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

Raw normalized facts:

```json
{
  "capabilities": [],
  "cicd": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.cicd.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "code_health": {
    "available": true,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sonarqube.unavailable",
        "reason": "SONAR_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [
      {
        "evidence_ids": [],
        "key": "fixme_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "max_blob_size",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 101484
      },
      {
        "evidence_ids": [],
        "key": "source_file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 6
      },
      {
        "evidence_ids": [],
        "key": "todo_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "unique_blob_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 18
      },
      {
        "evidence_ids": [],
        "key": "unique_commit_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "collected_at": "2026-09-21T20:31:24.691180Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "finding_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "git": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "author_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "authors_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "commits_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "head_sha",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "c8ef35841cadd038d709087705e5c1ccd09e42e6"
      },
      {
        "evidence_ids": [],
        "key": "history_complete",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "latest_activity_at",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "2025-04-24T05:43:58+00:00"
      },
      {
        "evidence_ids": [],
        "key": "ref",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "master"
      },
      {
        "evidence_ids": [],
        "key": "unique_commits",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "issues": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.issues.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "sonarqube.unavailable",
      "reason": "SONAR_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.appsec.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.cicd.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.issues.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    }
  ],
  "repository": {
    "canonical_uri": "https://github.com/Artem336600/TODO",
    "head_sha": "c8ef35841cadd038d709087705e5c1ccd09e42e6",
    "provider": "github",
    "ref": "HEAD",
    "repository_id": "github.todo",
    "schema_version": "repo-health.v1",
    "snapshot_id": null
  },
  "schema_version": "repo-health.v1",
  "security": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.appsec.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "source_snapshot_digest": null,
  "source_statuses": [
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git",
      "source_version": "git-cli",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git-sizer",
      "source_version": "json-v2",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git.todo-history",
      "source_version": null,
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "pydriller",
      "source_version": "2.12",
      "state": "available"
    },
    {
      "collected_at": "2026-09-21T20:31:25.502994Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sonarqube.unavailable",
          "reason": "SONAR_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sonarqube",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:25.502994Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.appsec.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.appsec",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:25.503995Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.cicd.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.cicd",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:25.503995Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.issues.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.issues",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "vale",
      "source_version": "vale-cli",
      "state": "available"
    }
  ],
  "source_versions": {
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "sourcecraft.cicd": "unavailable",
    "sourcecraft.issues": "unavailable",
    "vale": "vale-cli"
  }
}
```

### two-cucumbersfloating

Repository: [https://github.com/artemnoor/Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating)
Resolved HEAD: `8485aca29ee7d8f6902c4f6eda541d72153d8c94`
Machine-readable artifact: `artifacts/validation/20260921T-local-tools-full/repositories/two-cucumbersfloating.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 14.54 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 14.54; components=history=0.56, cadence=0.00, recency=0.02, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | warn | 80.00 | complete | high | 1 | code_health_score = (99.70*0.10) / 0.10 = 80.00 (active components only) |
| documentation | pass | 80.00 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 80.00; components=completeness=100.00, instructions=0.00, vale_quality=100.00, readability=100.00 |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

Raw normalized facts:

```json
{
  "capabilities": [],
  "cicd": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.cicd.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "code_health": {
    "available": true,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sonarqube.unavailable",
        "reason": "SONAR_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [
      {
        "evidence_ids": [],
        "key": "fixme_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "max_blob_size",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2969
      },
      {
        "evidence_ids": [],
        "key": "source_file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "todo_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "unique_blob_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 24
      },
      {
        "evidence_ids": [],
        "key": "unique_commit_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 11
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "collected_at": "2026-09-21T20:31:41.312600Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 5
      },
      {
        "evidence_ids": [],
        "key": "finding_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "git": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "author_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "authors_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "commits_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "head_sha",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "8485aca29ee7d8f6902c4f6eda541d72153d8c94"
      },
      {
        "evidence_ids": [],
        "key": "history_complete",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "latest_activity_at",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "2026-03-20T18:08:14+00:00"
      },
      {
        "evidence_ids": [],
        "key": "ref",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "develop"
      },
      {
        "evidence_ids": [],
        "key": "unique_commits",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 8
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "issues": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.issues.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "sonarqube.unavailable",
      "reason": "SONAR_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.appsec.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.cicd.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.issues.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    }
  ],
  "repository": {
    "canonical_uri": "https://github.com/artemnoor/Two-cucumbersfloating",
    "head_sha": "8485aca29ee7d8f6902c4f6eda541d72153d8c94",
    "provider": "github",
    "ref": "HEAD",
    "repository_id": "github.two-cucumbersfloating",
    "schema_version": "repo-health.v1",
    "snapshot_id": null
  },
  "schema_version": "repo-health.v1",
  "security": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.appsec.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "source_snapshot_digest": null,
  "source_statuses": [
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git",
      "source_version": "git-cli",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git-sizer",
      "source_version": "json-v2",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git.todo-history",
      "source_version": null,
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "pydriller",
      "source_version": "2.12",
      "state": "available"
    },
    {
      "collected_at": "2026-09-21T20:31:41.855615Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sonarqube.unavailable",
          "reason": "SONAR_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sonarqube",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:41.856130Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.appsec.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.appsec",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:41.856130Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.cicd.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.cicd",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:41.856130Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.issues.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.issues",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "vale",
      "source_version": "vale-cli",
      "state": "available"
    }
  ],
  "source_versions": {
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "sourcecraft.cicd": "unavailable",
    "sourcecraft.issues": "unavailable",
    "vale": "vale-cli"
  }
}
```

### andromeda

Repository: [https://github.com/artemnoor/andromeda](https://github.com/artemnoor/andromeda)
Resolved HEAD: `626c28a663c37d3313198ac7d06b8c4d9fe0c708`
Machine-readable artifact: `artifacts/validation/20260921T-local-tools-full/repositories/andromeda.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 90.69 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 90.69; components=history=1.00, cadence=1.00, recency=0.95, breadth=0.50, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | fail | 16.19 | complete | high | 1 | code_health_score = (16.19*0.10) / 0.10 = 16.19 (active components only) |
| documentation | warn | 80.00 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 80.00; components=completeness=100.00, instructions=0.00, vale_quality=100.00, readability=100.00 |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

Raw normalized facts:

```json
{
  "capabilities": [],
  "cicd": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.cicd.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "code_health": {
    "available": true,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sonarqube.unavailable",
        "reason": "SONAR_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [
      {
        "evidence_ids": [],
        "key": "fixme_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "max_blob_size",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 838072
      },
      {
        "evidence_ids": [],
        "key": "source_file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 730
      },
      {
        "evidence_ids": [],
        "key": "todo_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "unique_blob_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2517
      },
      {
        "evidence_ids": [],
        "key": "unique_commit_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 89
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "collected_at": "2026-09-21T20:31:45.531937Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 77
      },
      {
        "evidence_ids": [],
        "key": "finding_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "git": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "author_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "authors_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "commits_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 83
      },
      {
        "evidence_ids": [],
        "key": "head_sha",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "626c28a663c37d3313198ac7d06b8c4d9fe0c708"
      },
      {
        "evidence_ids": [],
        "key": "history_complete",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "latest_activity_at",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "2026-09-19T11:18:12+00:00"
      },
      {
        "evidence_ids": [],
        "key": "ref",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "main"
      },
      {
        "evidence_ids": [],
        "key": "unique_commits",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 83
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "issues": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.issues.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "sonarqube.unavailable",
      "reason": "SONAR_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.appsec.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.cicd.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.issues.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    }
  ],
  "repository": {
    "canonical_uri": "https://github.com/artemnoor/andromeda",
    "head_sha": "626c28a663c37d3313198ac7d06b8c4d9fe0c708",
    "provider": "github",
    "ref": "HEAD",
    "repository_id": "github.andromeda",
    "schema_version": "repo-health.v1",
    "snapshot_id": null
  },
  "schema_version": "repo-health.v1",
  "security": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.appsec.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "source_snapshot_digest": null,
  "source_statuses": [
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git",
      "source_version": "git-cli",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git-sizer",
      "source_version": "json-v2",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git.todo-history",
      "source_version": null,
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "pydriller",
      "source_version": "2.12",
      "state": "available"
    },
    {
      "collected_at": "2026-09-21T20:31:51.647028Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sonarqube.unavailable",
          "reason": "SONAR_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sonarqube",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:51.647028Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.appsec.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.appsec",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:51.647553Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.cicd.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.cicd",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:31:51.647553Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.issues.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.issues",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "vale",
      "source_version": "vale-cli",
      "state": "available"
    }
  ],
  "source_versions": {
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "sourcecraft.cicd": "unavailable",
    "sourcecraft.issues": "unavailable",
    "vale": "vale-cli"
  }
}
```

### ruff

Repository: [https://github.com/astral-sh/ruff](https://github.com/astral-sh/ruff)
Resolved HEAD: `e86121d0d16586508e38bbc52cef10a2e5f4c0f8`
Machine-readable artifact: `artifacts/validation/20260921T-local-tools-full/repositories/ruff.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 99.90 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 99.90; components=history=1.00, cadence=1.00, recency=1.00, breadth=1.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | fail | 0.00 | complete | high | 1 | code_health_score = (0.00*0.10) / 0.10 = 0.00 (active components only) |
| documentation | warn | 80.00 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 80.00; components=completeness=100.00, instructions=0.00, vale_quality=100.00, readability=100.00 |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

Raw normalized facts:

```json
{
  "capabilities": [],
  "cicd": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.cicd.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "code_health": {
    "available": true,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sonarqube.unavailable",
        "reason": "SONAR_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [
      {
        "evidence_ids": [],
        "key": "fixme_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 87
      },
      {
        "evidence_ids": [],
        "key": "max_blob_size",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 7005480
      },
      {
        "evidence_ids": [],
        "key": "source_file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 5082
      },
      {
        "evidence_ids": [],
        "key": "todo_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 811
      },
      {
        "evidence_ids": [],
        "key": "unique_blob_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 166627
      },
      {
        "evidence_ids": [],
        "key": "unique_commit_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 23635
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "collected_at": "2026-09-21T20:33:04.256399Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "file_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 718
      },
      {
        "evidence_ids": [],
        "key": "finding_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 69
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "git": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "author_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 948
      },
      {
        "evidence_ids": [],
        "key": "authors_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 117
      },
      {
        "evidence_ids": [],
        "key": "commits_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1504
      },
      {
        "evidence_ids": [],
        "key": "head_sha",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "e86121d0d16586508e38bbc52cef10a2e5f4c0f8"
      },
      {
        "evidence_ids": [],
        "key": "history_complete",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "latest_activity_at",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "2026-09-21T17:18:26+00:00"
      },
      {
        "evidence_ids": [],
        "key": "ref",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": "main"
      },
      {
        "evidence_ids": [],
        "key": "unique_commits",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 17313
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "issues": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.issues.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "sonarqube.unavailable",
      "reason": "SONAR_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.appsec.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.cicd.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "sourcecraft.issues.unavailable",
      "reason": "SOURCECRAFT_URL is not configured",
      "schema_version": "repo-health.v1"
    }
  ],
  "repository": {
    "canonical_uri": "https://github.com/astral-sh/ruff",
    "head_sha": "e86121d0d16586508e38bbc52cef10a2e5f4c0f8",
    "provider": "github",
    "ref": "HEAD",
    "repository_id": "github.ruff",
    "schema_version": "repo-health.v1",
    "snapshot_id": null
  },
  "schema_version": "repo-health.v1",
  "security": {
    "available": false,
    "limitations": [
      {
        "affected_scope": null,
        "code": "sourcecraft.appsec.unavailable",
        "reason": "SOURCECRAFT_URL is not configured",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "source_snapshot_digest": null,
  "source_statuses": [
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git",
      "source_version": "git-cli",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git-sizer",
      "source_version": "json-v2",
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "git.todo-history",
      "source_version": null,
      "state": "available"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "pydriller",
      "source_version": "2.12",
      "state": "available"
    },
    {
      "collected_at": "2026-09-21T20:33:54.963519Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sonarqube.unavailable",
          "reason": "SONAR_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sonarqube",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:33:54.963519Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.appsec.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.appsec",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:33:54.963519Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.cicd.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.cicd",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": "2026-09-21T20:33:54.963519Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "sourcecraft.issues.unavailable",
          "reason": "SOURCECRAFT_URL is not configured",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "sourcecraft.issues",
      "source_version": null,
      "state": "unavailable"
    },
    {
      "collected_at": null,
      "limitations": [],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "vale",
      "source_version": "vale-cli",
      "state": "available"
    }
  ],
  "source_versions": {
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "sourcecraft.cicd": "unavailable",
    "sourcecraft.issues": "unavailable",
    "vale": "vale-cli"
  }
}
```


## Performance

| Repository | Type | Clone ms | Collection ms | Normalization ms | Analyzer ms | Score engine ms | Total ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| andromeda | STRONG_USER | 3386 | 6888 | 4 | 7 | 0 | 10305 |
| codeslicer | STRONG_USER | 2879 | 7555 | 5 | 5 | 0 | 10457 |
| fastapi | GOLDEN_OSS | 15707 | 15865 | 5 | 4 | 0 | 31593 |
| freshly | WEAK | 1759 | 921 | 3 | 7 | 0 | 2714 |
| mvp-food | VERY_WEAK | 1293 | 3334 | 4 | 28 | 0 | 4736 |
| ocheredibm3 | MIXED | 8654 | 482 | 4 | 5 | 0 | 9157 |
| procsima-low-version | MIXED | 3983 | 960 | 4 | 5 | 0 | 4986 |
| pydantic | GOLDEN_OSS | 55877 | 10468 | 4 | 6 | 0 | 66374 |
| repo-health-analyzer-production | STRONG_USER | 21226 | 1760 | 2 | 5 | 0 | 23009 |
| ruff | GOLDEN_OSS | 37158 | 56131 | 4 | 4 | 0 | 93309 |
| todo | MIXED | 1448 | 883 | 3 | 8 | 0 | 2365 |
| two-cucumbersfloating | ADVERSARIAL | 1370 | 606 | 5 | 7 | 0 | 2004 |
| uv | GOLDEN_OSS | 58256 | 19822 | 4 | 4 | 0 | 78098 |

## SourceCraft-specific validation scope

Issues, CI/CD, and Security are SourceCraft-only in this product. This GitHub validation proves only that unavailable/partial states, coverage, confidence, and evidence semantics are preserved. A controlled SourceCraft fixture with safe synthetic findings is still required for live provider validation.

## Interpretation

Observed anomalies are evidence for follow-up investigation. This run intentionally does not modify weights, calibration-v2, Score Engine v1, security caps, coverage/confidence formulas, or analyzer formulas.
