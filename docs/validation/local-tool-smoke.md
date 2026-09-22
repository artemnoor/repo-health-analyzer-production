# Current Repo Health Engine Validation

This report records observed behavior of the existing production engine. It is not a calibration change and does not treat any absolute score as ground truth.

Engine validation status: **PASS WITH COVERAGE LIMITATIONS**
Safe to proceed to Recommendation Engine: **NO**
Reason: Do not proceed as the full validation gate until all 13 repositories complete without actual failures and a controlled SourceCraft fixture covers Issues/CI/CD/Security.

## Methodology

Each public GitHub URL was cloned into an isolated ignored checkout and run through the unchanged production composition root: Git/PyDriller/Vale/SonarQube/git-sizer/TODO collectors as available → normalized RepositoryFacts → six analyzers → ScoreEngineV1. GitHub Issues, GitHub Actions, CodeQL, Dependabot, and other GitHub APIs were never used as SourceCraft substitutes.

Run as-of: `2026-09-21T20:25:17.693325+00:00`; repositories attempted: `1`; artifacts: `artifacts/validation/20260921T-local-tools-smoke`

## Comparison table

| Repository | Type | Documentation | Activity | Code Health | Local Coverage | Overall state | Major observations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [ruff](https://github.com/astral-sh/ruff) | GOLDEN_OSS | 80.00 | 99.90 | 0.00 | 2/6 production capabilities live | INSUFFICIENT_DATA | cicd:partial/unavailable; code_health:partial/unavailable; issues:partial/unavailable; security:partial/unavailable |

## Hypotheses

| ID | Status | Expected relationship | Classification | Evidence/cause |
| --- | --- | --- | --- | --- |
| H1 | NOT_TESTABLE | MVP_FOOD should not outrank mature controls across categories | LIMITATION | available local category scores |
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

None recorded.

## Limitations

- `matrix`: SONAR_URL is not configured
- `matrix`: controlled SourceCraft fixture is required

## Manual deep-dives

### mvp-food

Repository: [None](None)
Resolved HEAD: `N/A`
Machine-readable artifact: `None`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A | N/A |

### todo

Repository: [None](None)
Resolved HEAD: `N/A`
Machine-readable artifact: `None`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A | N/A |

### two-cucumbersfloating

Repository: [None](None)
Resolved HEAD: `N/A`
Machine-readable artifact: `None`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A | N/A |

### andromeda

Repository: [None](None)
Resolved HEAD: `N/A`
Machine-readable artifact: `None`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| N/A | N/A | N/A | N/A | N/A | N/A | N/A |

### ruff

Repository: [https://github.com/astral-sh/ruff](https://github.com/astral-sh/ruff)
Resolved HEAD: `e86121d0d16586508e38bbc52cef10a2e5f4c0f8`
Machine-readable artifact: `artifacts/validation/20260921T-local-tools-smoke/repositories/ruff.json`

| Category | Status | Score | Coverage | Confidence | Evidence | Formula substitution |
| --- | --- | --- | --- | --- | --- | --- |
| activity | pass | 99.90 | complete | high | 1 | activity_score = 100*(0.25*history + 0.25*cadence + 0.35*recency + 0.15*breadth)*(0.25 + 0.75*integrity) = 99.90; components=history=1.00, cadence=1.00, recency=1.00, breadth=1.00, integrity=1.00 |
| cicd | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| code_health | fail | 0.00 | complete | high | 1 | code_health_score = (0.00*0.10) / 0.10 = 0.00 (active components only) |
| documentation | warn | 80.00 | complete | high | 1 | documentation_score = 0.40*completeness + 0.20*instructions + 0.25*vale_quality + 0.15*readability = 80.00; components=completeness=100.00, instructions=0.00, vale_quality=100.00, readability=100.00 |
| issues | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |
| security | skipped | N/A | unavailable | unknown | 0 | not computable from available facts; score remains null |


## Performance

| Repository | Type | Clone ms | Collection ms | Normalization ms | Analyzer ms | Score engine ms | Total ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ruff | GOLDEN_OSS | 42568 | 56663 | 5 | 8 | 0 | 99295 |

## SourceCraft-specific validation scope

Issues, CI/CD, and Security are SourceCraft-only in this product. This GitHub validation proves only that unavailable/partial states, coverage, confidence, and evidence semantics are preserved. A controlled SourceCraft fixture with safe synthetic findings is still required for live provider validation.

## Interpretation

Observed anomalies are evidence for follow-up investigation. This run intentionally does not modify weights, calibration-v2, Score Engine v1, security caps, coverage/confidence formulas, or analyzer formulas.
