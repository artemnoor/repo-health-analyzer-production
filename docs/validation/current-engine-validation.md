# Current Repo Health Engine Validation

> Historical GitHub-only validation snapshot. Issues and CI/CD were intentionally
> not exercised through GitHub APIs. Current production SourceCraft provider
> wiring and live evidence are documented in
> [external-providers-readiness.md](external-providers-readiness.md).

This report records observed behavior of the existing production engine. It is not a calibration change and does not treat any absolute score as ground truth.

Engine validation status: **PASS WITH EXTERNAL COVERAGE LIMITATIONS**
Safe to proceed to Recommendation Engine: **YES**
Reason: All 13 repositories completed without runner/data bugs, calibration questions, analysis failures, or clone failures. SourceCraft AppSec live coverage remains an explicit external follow-up if credentials are unavailable.

## Methodology

Each public GitHub URL was cloned into an isolated ignored checkout and run through the canonical production composition root (with the narrow Vale JSON compatibility fix recorded below): Git/PyDriller/Vale/SonarQube/git-sizer/TODO collectors as available → normalized RepositoryFacts → six analyzers → ScoreEngineV1. GitHub Issues, GitHub Actions, CodeQL, Dependabot, and other GitHub APIs were never used as SourceCraft substitutes.

Run as-of: `2026-09-21T19:34:07+00:00`; repositories attempted: `13`; artifacts: `artifacts/validation/20260922T-production-readiness-final`

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
- Activity determinism, documentation evidence, Code Health partial semantics, and production source-scope fixes are included; Score Engine v1 weights remain unchanged.

## Comparison table

| Repository | Type | Documentation | Activity | Code Health | Local Coverage | Overall state | Major observations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [MVP_FOOD](https://github.com/Artem336600/MVP_FOOD) | VERY_WEAK | 53.71 | 6.99 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Freshly](https://github.com/Artem336600/Freshly) | WEAK | 54.77 | 25.00 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [TODO](https://github.com/Artem336600/TODO) | MIXED | 76.01 | 4.41 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Ocheredibm3](https://github.com/artemnoor/Ocheredibm3) | MIXED | 60.44 | 16.78 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | artifacts=1; cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Procsima-low_version-](https://github.com/artemnoor/Procsima-low_version-) | MIXED | 70.37 | 20.84 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | artifacts=3; cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating) | ADVERSARIAL | 81.56 | 14.54 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [andromeda](https://github.com/artemnoor/andromeda) | STRONG_USER | 86.28 | 90.72 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [CodeSlicer](https://github.com/Artem336600/CodeSlicer) | STRONG_USER | 74.35 | 53.02 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [repo-health-analyzer-production](https://github.com/artemnoor/repo-health-analyzer-production) | STRONG_USER | 86.40 | 86.51 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [ruff](https://github.com/astral-sh/ruff) | GOLDEN_OSS | 64.48 | 99.93 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [uv](https://github.com/astral-sh/uv) | GOLDEN_OSS | 68.78 | 100.00 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | artifacts=5; cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [fastapi](https://github.com/fastapi/fastapi) | GOLDEN_OSS | 65.57 | 87.47 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [pydantic](https://github.com/pydantic/pydantic) | GOLDEN_OSS | 65.30 | 97.40 | N/A | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |

## Before/after baseline comparison

Baseline: `artifacts/validation/20260921T-local-tools-full/summary.json`; baseline status: `FAIL — BUG`

| Repository | Same HEAD | Documentation before→after | Activity before→after | Code Health before→after | Before outcome | After outcome |
| --- | --- | --- | --- | --- | --- | --- |
| mvp-food | YES | 80.00 → 53.71 (Δ -26.29) | 6.99 → 6.99 (Δ 0.00) | 80.00 → N/A (Δ N/A) | degraded | degraded |
| freshly | YES | 80.00 → 54.77 (Δ -25.23) | 25.00 → 25.00 (Δ 0.00) | 80.00 → N/A (Δ N/A) | degraded | degraded |
| todo | YES | 80.00 → 76.01 (Δ -3.99) | 4.41 → 4.41 (Δ 0.00) | 80.00 → N/A (Δ N/A) | degraded | degraded |
| ocheredibm3 | YES | 80.00 → 60.44 (Δ -19.56) | 16.78 → 16.78 (Δ 0.00) | 80.00 → N/A (Δ N/A) | degraded | degraded |
| procsima-low-version | YES | 80.00 → 70.37 (Δ -9.63) | 20.84 → 20.84 (Δ 0.00) | 0.00 → N/A (Δ N/A) | degraded | degraded |
| two-cucumbersfloating | YES | 80.00 → 81.56 (Δ 1.56) | 14.54 → 14.54 (Δ 0.00) | 80.00 → N/A (Δ N/A) | degraded | degraded |
| andromeda | YES | 80.00 → 86.28 (Δ 6.28) | 90.69 → 90.72 (Δ 0.03) | 16.19 → N/A (Δ N/A) | degraded | degraded |
| codeslicer | YES | 80.00 → 74.35 (Δ -5.65) | 53.02 → 53.02 (Δ 0.01) | 0.00 → N/A (Δ N/A) | degraded | degraded |
| repo-health-analyzer-production | YES | 80.00 → 86.40 (Δ 6.40) | 86.48 → 86.51 (Δ 0.03) | 0.00 → N/A (Δ N/A) | degraded | degraded |
| ruff | YES | 80.00 → 64.48 (Δ -15.52) | 99.90 → 99.93 (Δ 0.03) | 0.00 → N/A (Δ N/A) | degraded | degraded |
| uv | YES | 80.00 → 68.78 (Δ -11.22) | 99.98 → 100.00 (Δ 0.02) | 0.00 → N/A (Δ N/A) | degraded | degraded |
| fastapi | YES | 80.00 → 65.57 (Δ -14.43) | 87.45 → 87.47 (Δ 0.02) | 0.00 → N/A (Δ N/A) | degraded | degraded |
| pydantic | YES | 80.00 → 65.30 (Δ -14.70) | 97.37 → 97.40 (Δ 0.03) | 0.00 → N/A (Δ N/A) | degraded | degraded |

## Hypotheses

| ID | Status | Expected relationship | Classification | Evidence/cause |
| --- | --- | --- | --- | --- |
| H1 | PASS | MVP_FOOD should not outrank mature controls across categories | EXPECTED BEHAVIOR | available local category scores |
| H2 | PASS | Documentation should be noticeably higher than Activity | EXPECTED BEHAVIOR | TODO category scores |
| H3 | PASS | Good documentation may coexist with limited substantive product | EXPECTED BEHAVIOR | validation-only inventory plus available category results |
| H4 | PASS | Large mature repositories should not be systematically penalized only for size | EXPECTED BEHAVIOR | Code Health numeric availability and explicit partial coverage |
| H5 | PASS | Tiny repositories should not receive an unjustifiably high Code Health from absent complexity/duplication | EXPECTED BEHAVIOR | source inventory, core component evidence, and Code Health |
| H6 | PASS | Unavailable GitHub-only SourceCraft metrics must not become numeric zero | EXPECTED BEHAVIOR | SourceCraft-only category projections |
| H7 | PASS | Coverage/confidence must show SourceCraft was not checked on GitHub | EXPECTED BEHAVIOR | SourceCraft-only category coverage/confidence |
| H8 | PASS | Issues and CI/CD must not be mislabeled as SourceCraft-backed or populated from GitHub APIs | EXPECTED BEHAVIOR | production source mapping and unavailable category projections |
| H9 | PASS | Documentation should not collapse to one value across the corpus | EXPECTED BEHAVIOR | relative score variance |

## Anomalies and classifications

| Repository | Category | Class | Observed | Expected | Possible cause |
| --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A |

## Actual bugs

None recorded.

## Calibration questions

None recorded.

## Expected behavior

- `mvp-food`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `freshly`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `todo`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `ocheredibm3`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `procsima-low-version`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `two-cucumbersfloating`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `andromeda`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `codeslicer`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `repo-health-analyzer-production`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `ruff`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `uv`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `fastapi`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `pydantic`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated

## Limitations

- `matrix`: SONAR_URL is not configured
- `matrix`: controlled SourceCraft fixture is required

## Manual deep-dives

### mvp-food

Repository: [https://github.com/Artem336600/MVP_FOOD](https://github.com/Artem336600/MVP_FOOD)
Resolved HEAD: `27c20c152274f2a6f1421c1d45ec2105859d26bb`
Machine-readable artifact: `artifacts/validation/20260922T-production-readiness-final/repositories/mvp-food.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 6.99 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 6.99; components=history=0.28, cadence=0.00, recency=0.00, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | partial | low | 1 | not computable from available facts; score remains null |
| documentation | pass | 53.71 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 53.71; components=completeness=46.79, instructions=0.00, vale_quality=100.00, readability=66.67 |
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
        "code": "cicd.provider.unavailable",
        "reason": "No production provider is configured for this category",
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
  "collected_at": "2026-09-21T21:52:15.484009Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "analyzed_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "api_docs_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "changelog_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "completeness",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 46.78666666666666
      },
      {
        "evidence_ids": [],
        "key": "complex_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "contributing_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "discovered_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "docs_directory_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "fatal_count",
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
      },
      {
        "evidence_ids": [],
        "key": "has_instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "instruction_section_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0.0
      },
      {
        "evidence_ids": [],
        "key": "license_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "long_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "readability",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 66.66666666666666
      },
      {
        "evidence_ids": [],
        "key": "readme_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "readme_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 3
      },
      {
        "evidence_ids": [],
        "key": "suggestion_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "warning_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "weighted_finding_points",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0.0
      },
      {
        "evidence_ids": [],
        "key": "words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 3
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
        "code": "issues.provider.unavailable",
        "reason": "No production provider is configured for this category",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "cicd.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "issues.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
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
      "collected_at": "2026-09-21T21:52:15.484009Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "cicd.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "cicd.provider",
      "source_version": null,
      "state": "unavailable"
    },
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
      "collected_at": "2026-09-21T21:52:15.793842Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "issues.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "issues.provider",
      "source_version": null,
      "state": "unavailable"
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
      "collected_at": "2026-09-21T21:52:16.079753Z",
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
      "collected_at": "2026-09-21T21:52:16.080753Z",
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
    "cicd.provider": "unavailable",
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "issues.provider": "unavailable",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "vale": "vale-cli"
  }
}
```

### todo

Repository: [https://github.com/Artem336600/TODO](https://github.com/Artem336600/TODO)
Resolved HEAD: `c8ef35841cadd038d709087705e5c1ccd09e42e6`
Machine-readable artifact: `artifacts/validation/20260922T-production-readiness-final/repositories/todo.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 4.41 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 4.41; components=history=0.18, cadence=0.00, recency=0.00, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | partial | low | 1 | not computable from available facts; score remains null |
| documentation | pass | 76.01 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 76.01; components=completeness=66.67, instructions=75.00, vale_quality=100.00, readability=62.27 |
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
        "code": "cicd.provider.unavailable",
        "reason": "No production provider is configured for this category",
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
  "collected_at": "2026-09-21T21:52:20.447027Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "analyzed_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "api_docs_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "changelog_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "completeness",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 66.66666666666667
      },
      {
        "evidence_ids": [],
        "key": "complex_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 194
      },
      {
        "evidence_ids": [],
        "key": "contributing_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "discovered_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 2
      },
      {
        "evidence_ids": [],
        "key": "docs_directory_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "fatal_count",
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
      },
      {
        "evidence_ids": [],
        "key": "has_instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "instruction_section_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 3
      },
      {
        "evidence_ids": [],
        "key": "instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 75.0
      },
      {
        "evidence_ids": [],
        "key": "license_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "long_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 32
      },
      {
        "evidence_ids": [],
        "key": "readability",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 62.26548672566373
      },
      {
        "evidence_ids": [],
        "key": "readme_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "readme_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 513
      },
      {
        "evidence_ids": [],
        "key": "suggestion_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "warning_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "weighted_finding_points",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0.0
      },
      {
        "evidence_ids": [],
        "key": "words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 565
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
        "code": "issues.provider.unavailable",
        "reason": "No production provider is configured for this category",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "cicd.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "issues.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
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
      "collected_at": "2026-09-21T21:52:20.447027Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "cicd.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "cicd.provider",
      "source_version": null,
      "state": "unavailable"
    },
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
      "collected_at": "2026-09-21T21:52:20.808873Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "issues.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "issues.provider",
      "source_version": null,
      "state": "unavailable"
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
      "collected_at": "2026-09-21T21:52:20.905910Z",
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
      "collected_at": "2026-09-21T21:52:20.905910Z",
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
    "cicd.provider": "unavailable",
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "issues.provider": "unavailable",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "vale": "vale-cli"
  }
}
```

### two-cucumbersfloating

Repository: [https://github.com/artemnoor/Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating)
Resolved HEAD: `8485aca29ee7d8f6902c4f6eda541d72153d8c94`
Machine-readable artifact: `artifacts/validation/20260922T-production-readiness-final/repositories/two-cucumbersfloating.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 14.54 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 14.54; components=history=0.56, cadence=0.00, recency=0.02, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | partial | low | 1 | not computable from available facts; score remains null |
| documentation | pass | 81.56 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 81.56; components=completeness=73.33, instructions=75.00, vale_quality=100.00, readability=81.49 |
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
        "code": "cicd.provider.unavailable",
        "reason": "No production provider is configured for this category",
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
  "collected_at": "2026-09-21T21:52:30.888658Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "analyzed_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 5
      },
      {
        "evidence_ids": [],
        "key": "api_docs_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "changelog_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "completeness",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 73.33333333333334
      },
      {
        "evidence_ids": [],
        "key": "complex_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 120
      },
      {
        "evidence_ids": [],
        "key": "contributing_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "discovered_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 5
      },
      {
        "evidence_ids": [],
        "key": "docs_directory_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "fatal_count",
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
      },
      {
        "evidence_ids": [],
        "key": "has_instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "instruction_section_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 3
      },
      {
        "evidence_ids": [],
        "key": "instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 75.0
      },
      {
        "evidence_ids": [],
        "key": "license_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "long_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 23
      },
      {
        "evidence_ids": [],
        "key": "readability",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 81.49377593360997
      },
      {
        "evidence_ids": [],
        "key": "readme_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "readme_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 102
      },
      {
        "evidence_ids": [],
        "key": "suggestion_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "warning_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "weighted_finding_points",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0.0
      },
      {
        "evidence_ids": [],
        "key": "words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 723
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
        "code": "issues.provider.unavailable",
        "reason": "No production provider is configured for this category",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "cicd.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "issues.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
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
      "collected_at": "2026-09-21T21:52:30.888658Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "cicd.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "cicd.provider",
      "source_version": null,
      "state": "unavailable"
    },
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
      "collected_at": "2026-09-21T21:52:31.195959Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "issues.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "issues.provider",
      "source_version": null,
      "state": "unavailable"
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
      "collected_at": "2026-09-21T21:52:31.288473Z",
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
      "collected_at": "2026-09-21T21:52:31.288473Z",
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
    "cicd.provider": "unavailable",
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "issues.provider": "unavailable",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "vale": "vale-cli"
  }
}
```

### andromeda

Repository: [https://github.com/artemnoor/andromeda](https://github.com/artemnoor/andromeda)
Resolved HEAD: `626c28a663c37d3313198ac7d06b8c4d9fe0c708`
Machine-readable artifact: `artifacts/validation/20260922T-production-readiness-final/repositories/andromeda.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 90.72 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 90.72; components=history=1.00, cadence=1.00, recency=0.95, breadth=0.50, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | partial | low | 1 | not computable from available facts; score remains null |
| documentation | warn | 86.28 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 86.28; components=completeness=86.67, instructions=100.00, vale_quality=89.99, readability=60.78 |
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
        "code": "cicd.provider.unavailable",
        "reason": "No production provider is configured for this category",
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
  "collected_at": "2026-09-21T21:52:34.786726Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "analyzed_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 77
      },
      {
        "evidence_ids": [],
        "key": "api_docs_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "changelog_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "completeness",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 86.66666666666667
      },
      {
        "evidence_ids": [],
        "key": "complex_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 24645
      },
      {
        "evidence_ids": [],
        "key": "contributing_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "discovered_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 77
      },
      {
        "evidence_ids": [],
        "key": "docs_directory_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "fatal_count",
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
      },
      {
        "evidence_ids": [],
        "key": "has_instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "instruction_section_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 75
      },
      {
        "evidence_ids": [],
        "key": "instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 100.0
      },
      {
        "evidence_ids": [],
        "key": "license_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "long_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 5576
      },
      {
        "evidence_ids": [],
        "key": "readability",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 60.77935180125268
      },
      {
        "evidence_ids": [],
        "key": "readme_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "readme_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1709
      },
      {
        "evidence_ids": [],
        "key": "suggestion_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "warning_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1
      },
      {
        "evidence_ids": [],
        "key": "weighted_finding_points",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1.0
      },
      {
        "evidence_ids": [],
        "key": "words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 71367
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
        "code": "issues.provider.unavailable",
        "reason": "No production provider is configured for this category",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "cicd.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "issues.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
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
      "collected_at": "2026-09-21T21:52:34.786726Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "cicd.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "cicd.provider",
      "source_version": null,
      "state": "unavailable"
    },
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
      "collected_at": "2026-09-21T21:52:39.484084Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "issues.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "issues.provider",
      "source_version": null,
      "state": "unavailable"
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
      "collected_at": "2026-09-21T21:52:39.602601Z",
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
      "collected_at": "2026-09-21T21:52:39.602601Z",
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
    "cicd.provider": "unavailable",
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "issues.provider": "unavailable",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "vale": "vale-cli"
  }
}
```

### ruff

Repository: [https://github.com/astral-sh/ruff](https://github.com/astral-sh/ruff)
Resolved HEAD: `e86121d0d16586508e38bbc52cef10a2e5f4c0f8`
Machine-readable artifact: `artifacts/validation/20260922T-production-readiness-final/repositories/ruff.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 99.93 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 99.93; components=history=1.00, cadence=1.00, recency=1.00, breadth=1.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | partial | low | 1 | not computable from available facts; score remains null |
| documentation | warn | 64.48 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 64.48; components=completeness=86.67, instructions=100.00, vale_quality=0.00, readability=65.45 |
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
        "code": "cicd.provider.unavailable",
        "reason": "No production provider is configured for this category",
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
        "value": 166644
      },
      {
        "evidence_ids": [],
        "key": "unique_commit_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 23644
      }
    ],
    "schema_version": "repo-health.v1"
  },
  "collected_at": "2026-09-21T21:54:05.042639Z",
  "documentation": {
    "available": true,
    "limitations": [],
    "observations": [
      {
        "evidence_ids": [],
        "key": "analyzed_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 718
      },
      {
        "evidence_ids": [],
        "key": "api_docs_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "changelog_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "completeness",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 86.66666666666667
      },
      {
        "evidence_ids": [],
        "key": "complex_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1103298
      },
      {
        "evidence_ids": [],
        "key": "contributing_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "discovered_files",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 718
      },
      {
        "evidence_ids": [],
        "key": "docs_directory_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "error_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "fatal_count",
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
      },
      {
        "evidence_ids": [],
        "key": "has_instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "instruction_section_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 235
      },
      {
        "evidence_ids": [],
        "key": "instructions",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 100.0
      },
      {
        "evidence_ids": [],
        "key": "license_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": false
      },
      {
        "evidence_ids": [],
        "key": "long_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 468888
      },
      {
        "evidence_ids": [],
        "key": "readability",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 65.45188384845376
      },
      {
        "evidence_ids": [],
        "key": "readme_present",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": true
      },
      {
        "evidence_ids": [],
        "key": "readme_words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 15119
      },
      {
        "evidence_ids": [],
        "key": "suggestion_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 0
      },
      {
        "evidence_ids": [],
        "key": "warning_count",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 69
      },
      {
        "evidence_ids": [],
        "key": "weighted_finding_points",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 69.0
      },
      {
        "evidence_ids": [],
        "key": "words",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 4007833
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
        "value": 116
      },
      {
        "evidence_ids": [],
        "key": "commits_90d",
        "schema_version": "repo-health.v1",
        "unit": null,
        "value": 1493
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
        "code": "issues.provider.unavailable",
        "reason": "No production provider is configured for this category",
        "schema_version": "repo-health.v1"
      }
    ],
    "observations": [],
    "schema_version": "repo-health.v1"
  },
  "limitations": [
    {
      "affected_scope": null,
      "code": "cicd.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
    {
      "affected_scope": null,
      "code": "issues.provider.unavailable",
      "reason": "No production provider is configured for this category",
      "schema_version": "repo-health.v1"
    },
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
      "collected_at": "2026-09-21T21:54:05.042639Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "cicd.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "cicd.provider",
      "source_version": null,
      "state": "unavailable"
    },
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
      "collected_at": "2026-09-21T21:54:45.110290Z",
      "limitations": [
        {
          "affected_scope": null,
          "code": "issues.provider.unavailable",
          "reason": "No production provider is configured for this category",
          "schema_version": "repo-health.v1"
        }
      ],
      "schema_version": "repo-health.v1",
      "snapshot_digest": null,
      "source_id": "issues.provider",
      "source_version": null,
      "state": "unavailable"
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
      "collected_at": "2026-09-21T21:54:47.421675Z",
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
      "collected_at": "2026-09-21T21:54:47.422675Z",
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
    "cicd.provider": "unavailable",
    "git": "git-cli",
    "git-sizer": "json-v2",
    "git.todo-history": "local-scan-v1",
    "issues.provider": "unavailable",
    "pydriller": "2.12",
    "sonarqube": "unavailable",
    "sourcecraft.appsec": "unavailable",
    "vale": "vale-cli"
  }
}
```


## Performance

| Repository | Type | Clone ms | Collection ms | Normalization ms | Analyzer ms | Score engine ms | Total ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mvp-food | VERY_WEAK | 1129 | 645 | 6 | 7 | 0 | 1821 |
| freshly | WEAK | 1418 | 556 | 7 | 6 | 0 | 2002 |
| todo | MIXED | 1192 | 513 | 5 | 7 | 0 | 1733 |
| ocheredibm3 | MIXED | 1179 | 471 | 6 | 8 | 0 | 1679 |
| procsima-low-version | MIXED | 4219 | 860 | 7 | 7 | 0 | 5105 |
| two-cucumbersfloating | ADVERSARIAL | 1163 | 447 | 5 | 6 | 0 | 1634 |
| andromeda | STRONG_USER | 2832 | 5284 | 7 | 6 | 0 | 8140 |
| codeslicer | STRONG_USER | 2361 | 6926 | 6 | 10 | 0 | 9320 |
| repo-health-analyzer-production | STRONG_USER | 24334 | 1399 | 6 | 7 | 0 | 25760 |
| ruff | GOLDEN_OSS | 44142 | 51434 | 6 | 7 | 0 | 95603 |
| uv | GOLDEN_OSS | 29896 | 13500 | 6 | 7 | 0 | 43432 |
| fastapi | GOLDEN_OSS | 10559 | 15406 | 6 | 7 | 0 | 25995 |
| pydantic | GOLDEN_OSS | 52202 | 7790 | 7 | 7 | 0 | 60020 |

## SourceCraft-specific validation scope

Security is SourceCraft AppSec-only in this product. Issues and CI/CD have no configured production provider and are not substituted with GitHub APIs. This GitHub validation proves unavailable/partial state, coverage, confidence, and evidence semantics; a controlled SourceCraft fixture with safe synthetic findings is still required for live AppSec provider validation.

## Interpretation

Observed anomalies are evidence for follow-up investigation. This run intentionally does not modify weights, calibration-v2, Score Engine v1, security caps, coverage/confidence formulas, or analyzer formulas.
