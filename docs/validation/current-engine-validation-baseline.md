# Current Repo Health Engine Validation

> Historical GitHub-only validation snapshot. Issues and CI/CD were intentionally
> not exercised through GitHub APIs. Current production SourceCraft provider
> wiring and live evidence are documented in
> [external-providers-readiness.md](external-providers-readiness.md).

This report records observed behavior of the existing production engine. It is not a calibration change and does not treat any absolute score as ground truth.

Engine validation status: **PASS WITH ANOMALIES**
Safe to proceed to Recommendation Engine: **YES**
Reason: All 13 repositories completed without runner/data BUG, analysis failure, or clone failure; SourceCraft live coverage still requires a controlled fixture.

## Methodology

Each public GitHub URL was cloned into an isolated ignored checkout and run through the unchanged production composition root: Git/PyDriller/Vale/SonarQube/git-sizer/TODO collectors as available → normalized RepositoryFacts → six analyzers → ScoreEngineV1. GitHub Issues, GitHub Actions, CodeQL, Dependabot, and other GitHub APIs were never used as SourceCraft substitutes.

Run as-of: `2026-09-21T12:00:00+00:00`; repositories attempted: `13`; artifacts: `artifacts/validation/20260921T193407Z-420d811d`

## Comparison table

| Repository | Type | Documentation | Activity | Code Health | Local Coverage | Overall state | Major observations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [MVP_FOOD](https://github.com/Artem336600/MVP_FOOD) | VERY_WEAK | N/A | 6.99 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Freshly](https://github.com/Artem336600/Freshly) | WEAK | N/A | 25.00 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [TODO](https://github.com/Artem336600/TODO) | MIXED | N/A | 4.41 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Ocheredibm3](https://github.com/artemnoor/Ocheredibm3) | MIXED | N/A | 16.78 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | artifacts=1; cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Procsima-low_version-](https://github.com/artemnoor/Procsima-low_version-) | MIXED | N/A | 20.84 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | artifacts=3; cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating) | ADVERSARIAL | N/A | 14.54 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [andromeda](https://github.com/artemnoor/andromeda) | STRONG_USER | N/A | 90.72 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [CodeSlicer](https://github.com/Artem336600/CodeSlicer) | STRONG_USER | N/A | 53.02 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [repo-health-analyzer-production](https://github.com/artemnoor/repo-health-analyzer-production) | STRONG_USER | N/A | 86.51 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [ruff](https://github.com/astral-sh/ruff) | GOLDEN_OSS | N/A | 99.93 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [uv](https://github.com/astral-sh/uv) | GOLDEN_OSS | N/A | 99.83 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | artifacts=5; cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [fastapi](https://github.com/fastapi/fastapi) | GOLDEN_OSS | N/A | 87.47 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |
| [pydantic](https://github.com/pydantic/pydantic) | GOLDEN_OSS | N/A | 97.40 | N/A | 1/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; documentation:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |

## Hypotheses

| ID | Status | Expected relationship | Classification | Evidence/cause |
| --- | --- | --- | --- | --- |
| H1 | PASS | MVP_FOOD should not outrank mature controls across categories | EXPECTED BEHAVIOR | available local category scores |
| H2 | NOT_TESTABLE | Documentation should be noticeably higher than Activity | LIMITATION | Vale or Git-derived category unavailable |
| H3 | NOT_TESTABLE | Good documentation may coexist with limited substantive product | LIMITATION | validation-only inventory plus available category results |
| H4 | NOT_TESTABLE | Large mature repositories should not be systematically penalized only for size | LIMITATION | Code Health numeric availability |
| H5 | NOT_TESTABLE | Tiny repositories should not receive an unjustifiably high Code Health from absent complexity/duplication | LIMITATION | source inventory and Code Health |
| H6 | PASS | Unavailable GitHub-only SourceCraft metrics must not become numeric zero | EXPECTED BEHAVIOR | SourceCraft-only category projections |
| H7 | PASS | Coverage/confidence must show SourceCraft was not checked on GitHub | EXPECTED BEHAVIOR | SourceCraft-only category coverage/confidence |

## Anomalies and classifications

| Repository | Category | Class | Observed | Expected | Possible cause |
| --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A |

## Actual bugs

None recorded.

## Calibration questions

None recorded.

## Expected behavior

- `freshly`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
- `todo`: This behavior is protected by the golden TODO-only Code Health test; no score is fabricated
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

- `matrix`: optional executable is unavailable
- `matrix`: optional executable is unavailable
- `matrix`: SONAR_URL is not configured
- `matrix`: controlled SourceCraft fixture is required

## Manual deep-dives

### mvp-food

Repository: [https://github.com/Artem336600/MVP_FOOD](https://github.com/Artem336600/MVP_FOOD)
Resolved HEAD: `27c20c152274f2a6f1421c1d45ec2105859d26bb`
Machine-readable artifact: `artifacts/validation/20260921T193407Z-420d811d/repositories/mvp-food.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 6.99 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 6.99; components=history=0.28, cadence=0.00, recency=0.00, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| documentation | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

### todo

Repository: [https://github.com/Artem336600/TODO](https://github.com/Artem336600/TODO)
Resolved HEAD: `c8ef35841cadd038d709087705e5c1ccd09e42e6`
Machine-readable artifact: `artifacts/validation/20260921T193407Z-420d811d/repositories/todo.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 4.41 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 4.41; components=history=0.18, cadence=0.00, recency=0.00, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | complete | low | 1 | not computable from available facts; score remains null |
| documentation | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

### two-cucumbersfloating

Repository: [https://github.com/artemnoor/Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating)
Resolved HEAD: `8485aca29ee7d8f6902c4f6eda541d72153d8c94`
Machine-readable artifact: `artifacts/validation/20260921T193407Z-420d811d/repositories/two-cucumbersfloating.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | fail | 14.54 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 14.54; components=history=0.56, cadence=0.00, recency=0.02, breadth=0.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | complete | low | 1 | not computable from available facts; score remains null |
| documentation | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

### andromeda

Repository: [https://github.com/artemnoor/andromeda](https://github.com/artemnoor/andromeda)
Resolved HEAD: `626c28a663c37d3313198ac7d06b8c4d9fe0c708`
Machine-readable artifact: `artifacts/validation/20260921T193407Z-420d811d/repositories/andromeda.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 90.72 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 90.72; components=history=1.00, cadence=1.00, recency=0.95, breadth=0.50, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | complete | low | 1 | not computable from available facts; score remains null |
| documentation | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |

### ruff

Repository: [https://github.com/astral-sh/ruff](https://github.com/astral-sh/ruff)
Resolved HEAD: `e86121d0d16586508e38bbc52cef10a2e5f4c0f8`
Machine-readable artifact: `artifacts/validation/20260921T193407Z-420d811d/repositories/ruff.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 99.93 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 99.93; components=history=1.00, cadence=1.00, recency=1.00, breadth=1.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | inconclusive | N/A | complete | low | 1 | not computable from available facts; score remains null |
| documentation | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |


## Performance

| Repository | Type | Clone ms | Collection ms | Analyzer ms | Total ms |
| --- | --- | --- | --- | --- | --- |
| mvp-food | VERY_WEAK | 1131 | 427 | 4 | 1668 |
| freshly | WEAK | 1297 | 201 | 4 | 1567 |
| todo | MIXED | 1170 | 207 | 4 | 1451 |
| ocheredibm3 | MIXED | 1117 | 149 | 3 | 1333 |
| procsima-low-version | MIXED | 4213 | 336 | 4 | 4624 |
| two-cucumbersfloating | ADVERSARIAL | 1213 | 172 | 4 | 1456 |
| andromeda | STRONG_USER | 2713 | 3582 | 4 | 6375 |
| codeslicer | STRONG_USER | 2571 | 3800 | 4 | 6444 |
| repo-health-analyzer-production | STRONG_USER | 19445 | 673 | 4 | 20192 |
| ruff | GOLDEN_OSS | 44817 | 40825 | 5 | 85753 |
| uv | GOLDEN_OSS | 29006 | 9661 | 4 | 38740 |
| fastapi | GOLDEN_OSS | 13792 | 7708 | 5 | 21572 |
| pydantic | GOLDEN_OSS | 66404 | 5962 | 4 | 72441 |

## SourceCraft-specific validation scope

Issues, CI/CD, and Security are SourceCraft-only in this product. This GitHub validation proves only that unavailable/partial states, coverage, confidence, and evidence semantics are preserved. A controlled SourceCraft fixture with safe synthetic findings is still required for live provider validation.

## Interpretation

Observed anomalies are evidence for follow-up investigation. This run intentionally does not modify weights, calibration-v2, Score Engine v1, security caps, coverage/confidence formulas, or analyzer formulas.
