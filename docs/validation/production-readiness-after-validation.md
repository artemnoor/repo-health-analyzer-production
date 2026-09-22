# Repo Health Analyzer — Production Readiness After Validation

## Verdict

**ENGINE VALIDATION STATUS: PASS WITH EXTERNAL COVERAGE LIMITATIONS**

**SAFE TO PROCEED TO RECOMMENDATION ENGINE: YES, with explicit external follow-up.**

The exact 13-repository GitHub corpus completed with zero runner/data bugs, zero
calibration questions, zero outliers, and deterministic repeated projections. This
does not claim live SourceCraft AppSec or SonarQube coverage: both were unavailable
in the validation environment and remain explicit limitations.

Full generated report: [current-engine-validation.md](current-engine-validation.md)

Machine-readable result: [summary.json](../../artifacts/validation/20260922T-production-readiness-final/summary.json)

Generated Markdown summary: [summary.md](../../artifacts/validation/20260922T-production-readiness-final/summary.md)

## Verification result

| Check | Result | Evidence |
| --- | --- | --- |
| Exact corpus | PASS | 13/13 repositories; immutable HEADs captured |
| Repeat determinism | PASS | 13/13 repeated projections PASS with fixed `as_of` |
| Activity wall-clock isolation | PASS | `AnalysisRequest.as_of` drives recency; collection timestamps are audit-only |
| Documentation variance | PASS | Documentation scores range from 53.71 to 86.40; H9 PASS |
| Code Health missing-data semantics | PASS | No numeric Code Health score without SonarQube core evidence; H4/H5 PASS |
| SourceCraft scope | PASS | GitHub Issues/Actions were not substituted; Security remains AppSec-only; H6-H8 PASS |
| Hypotheses | PASS | H1-H9 all PASS |
| Actual bugs | PASS | 0 |
| Full test suite | PASS | 119 passed, 1 external Starlette deprecation warning |
| Static/tooling gates | PASS | Ruff, format, compileall, uv lock, uv sync, git diff --check |
| SonarQube live coverage | LIMITATION | `SONAR_URL` not configured; Code Health remains honest partial/inconclusive |
| SourceCraft AppSec live coverage | LIMITATION | `SOURCECRAFT_URL` not configured; controlled fixture required |

## What changed in this readiness pass

- Activity scoring now uses explicit `AnalysisRequest.as_of`, removing hidden
  wall-clock drift while preserving `collected_at` as provenance metadata.
- Vale collection now records bounded, deterministic documentation-surface facts
  and parses the official file-keyed JSON shape; frozen Documentation weights are
  unchanged.
- Code Health no longer treats git-sizer/TODO-only facts as a complete quality
  score. Missing SonarQube produces a truthful partial/inconclusive result with
  retained structural evidence.
- Production wiring keeps SourceCraft AppSec as the only configured SourceCraft
  category. Issues and CI/CD are explicit unavailable categories until a real
  production provider is configured.
- Validation now checks deterministic repeat projections, missing-versus-zero,
  documentation collapse, tiny-repository over-scoring, size inversion, evidence
  consistency, and the exact SourceCraft scope.
- Score Engine v1 weights, security caps, calibration-v2 formulas, and complete
  data golden parity were not changed.

## Issue resolution matrix

| Issue | Before | Fix | After | Evidence |
| --- | --- | --- | --- | --- |
| Activity nondeterminism | Recency used wall-clock collection time and drifted between runs | Use explicit `AnalysisRequest.as_of` for scoring; retain collection time only as audit metadata | 13/13 repeated projections deterministic | `tests/unit/repo_health/test_activity_determinism.py`; matrix `determinism` fields |
| Documentation collapse | Most repositories scored exactly 80 despite materially different documentation surfaces | Add bounded checkout-backed surface facts and preserve Vale findings as quality evidence | 13 distinct Documentation scores, 53.71–86.40 | H9 PASS; `tests/unit/repo_health/test_documentation_analyzer.py` |
| Code Health partial inversion | Tiny repositories could receive 80 while mature repositories received 0 when SonarQube was absent | Require SonarQube core evidence for a numeric quality score; keep git-sizer/TODO as diagnostics | No fabricated numeric Code Health score without SonarQube; H4/H5 PASS | `tests/unit/repo_health/test_code_health_partial.py`; corpus JSON |
| Partial overconfidence | Missing core engines could appear complete/high-confidence | Add explicit capability-based coverage and confidence reasons | Code Health is `partial`/`low` when SonarQube is unavailable | category projections in `summary.json` |
| SourceCraft scope ambiguity | Validation labels could imply Issues/CI/CD were SourceCraft-backed | Wire AppSec only; mark Issues/CI/CD as no configured production provider | H6–H8 PASS; no GitHub API substitution | runtime composition tests and matrix source labels |
| H5 validation contradiction | The gate could pass while a tiny repository had a numeric Code Health score | Detect numeric Code Health without core components as an anomaly; add H5 regression tests | H5 PASS with inconclusive tiny Code Health | `tests/integration/validation/test_validation_lab.py` |

## Calibration changes

No frozen scoring calibration was changed. Documentation received additional
source-backed input facts, while Code Health changed only its missing-evidence
policy. Score Engine v1 weights, security caps, calibration-v2 constants, and
complete-data golden parity remain unchanged.

## Corpus comparison

| Repository | Type | Documentation | Activity | Code Health |
| --- | --- | ---: | ---: | ---: |
| [MVP_FOOD](https://github.com/Artem336600/MVP_FOOD) | VERY_WEAK | 53.71 | 6.99 | N/A |
| [Freshly](https://github.com/Artem336600/Freshly) | WEAK | 54.77 | 25.00 | N/A |
| [TODO](https://github.com/Artem336600/TODO) | MIXED | 76.01 | 4.41 | N/A |
| [Ocheredibm3](https://github.com/artemnoor/Ocheredibm3) | MIXED | 60.44 | 16.78 | N/A |
| [Procsima-low_version-](https://github.com/artemnoor/Procsima-low_version-) | MIXED | 70.37 | 20.84 | N/A |
| [Two-cucumbersfloating](https://github.com/artemnoor/Two-cucumbersfloating) | ADVERSARIAL | 81.56 | 14.54 | N/A |
| [andromeda](https://github.com/artemnoor/andromeda) | STRONG_USER | 86.28 | 90.72 | N/A |
| [CodeSlicer](https://github.com/Artem336600/CodeSlicer) | STRONG_USER | 74.35 | 53.02 | N/A |
| [repo-health-analyzer-production](https://github.com/artemnoor/repo-health-analyzer-production) | STRONG_USER | 86.40 | 86.51 | N/A |
| [ruff](https://github.com/astral-sh/ruff) | GOLDEN_OSS | 64.48 | 99.93 | N/A |
| [uv](https://github.com/astral-sh/uv) | GOLDEN_OSS | 68.78 | 100.00 | N/A |
| [fastapi](https://github.com/fastapi/fastapi) | GOLDEN_OSS | 65.57 | 87.47 | N/A |
| [pydantic](https://github.com/pydantic/pydantic) | GOLDEN_OSS | 65.30 | 97.40 | N/A |

`N/A` is intentional: SonarQube was unavailable, so Code Health does not
fabricate a score from missing core evidence.

## Manual deep-dives

The generated report contains raw facts, normalized observations, component
values, formula substitutions, evidence, limitations, and final results for:

- [MVP_FOOD](../../artifacts/validation/20260922T-production-readiness-final/repositories/mvp-food.json)
- [TODO](../../artifacts/validation/20260922T-production-readiness-final/repositories/todo.json)
- [Two-cucumbersfloating](../../artifacts/validation/20260922T-production-readiness-final/repositories/two-cucumbersfloating.json)
- [andromeda](../../artifacts/validation/20260922T-production-readiness-final/repositories/andromeda.json)
- [ruff](../../artifacts/validation/20260922T-production-readiness-final/repositories/ruff.json)

## Anomalies and actual bugs

No anomalies remain after the final validation gate. Actual bugs: **0**.

The first final-matrix attempt exposed one validation-gate threshold issue in H3,
not a product scoring issue. It was corrected to recognize the intended adversarial
case (good documentation with a small historical/product surface), covered by a
regression test, and the complete corpus was rerun.

## Remaining external limitations

1. Run SonarQube against a controlled fixture to obtain Code Health component
   scores and complete coverage.
2. Run a controlled SourceCraft fixture with safe synthetic AppSec findings to
   verify `/v1/scans → /v1/defect-groups → /v1/findings` live behavior.
3. GitHub-only validation intentionally does not use GitHub Issues or Actions as
   substitutes for SourceCraft providers.

## Accepted trade-offs and follow-up tasks

- Code Health is intentionally `N/A`/inconclusive without SonarQube rather than
  presenting a misleading partial score.
- GitHub-only runs intentionally leave Issues, CI/CD, and Security unavailable;
  this is a data-source boundary, not a zero result.
- Follow-up: run SonarQube against a controlled fixture and verify live AppSec
  against a controlled SourceCraft fixture with safe synthetic findings.
- Follow-up: keep the validation corpus rerunnable with the pinned tool manifest
  and fixed `as_of` for future engine changes.

## Reproduction commands

```powershell
$env:VALE_PATH='C:\\rhvl-tools-20260921\\bin\\vale.exe'
$env:GIT_SIZER_PATH='C:\\rhvl-tools-20260921\\bin\\git-sizer.exe'
uv run python scripts/validation/run_validation_matrix.py `
  --output-root artifacts/validation/20260922T-production-readiness-final `
  --checkout-root C:\\rh-validation-checkouts-20260922-final `
  --as-of 2026-09-21T19:34:07Z `
  --baseline-summary artifacts/validation/20260921T-local-tools-full/summary.json `
  --report-path docs/validation/current-engine-validation.md
```

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests scripts
uv lock --check
uv sync --locked
git diff --check
```
