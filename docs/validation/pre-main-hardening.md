# Pre-main production hardening

Status: implementation and verification report for the current task branch.

This hardening closes context and provenance gaps without changing formulas,
weights, calibration-v2 policy, security caps or ScoreEngineV1. It does not
implement the Recommendation Engine and does not merge or push the branch.

## Requirement matrix

| Issue | Before | Implemented | Verified by | Remaining limitation |
| --- | --- | --- | --- | --- |
| Assessment scope was implicit | A configured SourceCraft capability could be selected without a typed scope | `AssessmentProfile.PUBLIC` and `OWNER_EXTENDED` flow through request, facts, category, score and persisted envelope | contract, profile-gating, API and composition tests | Trusted identity provider is upstream of this API |
| Yandex ID and PAT boundary was implicit | Request context did not distinguish user identity from provider authorization | `AuthorizationContext` carries only identity subject, access state, presence boolean and safe scopes; PAT remains environment-only | contract serialization/redaction and API rejection tests | Yandex ID middleware is not part of this backend task |
| PUBLIC could consume owner data | Collection used capability configuration as the only decision | PUBLIC excludes SourceCraft owner collectors before network calls; OWNER_EXTENDED requires trusted identity plus authorized access | profile integration test and runtime matrix | PUBLIC SourceCraft Issues/CI/AppSec are explicitly unavailable by policy |
| AppSec no-scan and failed states were ambiguous | Empty/failed lifecycle could be interpreted as ordinary zero findings | `AppSecScanState` distinguishes no scan, finished zero, finished with findings, failed, unavailable and partial | adapter lifecycle fixtures, analyzer boundary tests | Live AppSec state still depends on SourceCraft availability |
| Partial AppSec was underspecified | Group failure had only generic partial observations | `SecurityFacts.scan_state`, coverage/confidence and limitations preserve the partial chain | partial group adapter test and security result path | Finding-level semantics depend on provider payload quality |
| Contributor identity could be over-interpreted | Only normalized author names were visible | Existing name counts remain formula inputs; bounded in-memory email sanity checks expose ambiguity without merging or persisting PII | contributor identity unit tests and PyDriller collector path | SourceCraft stable contributor IDs are not available in this path |
| API and Worker context could diverge | Profile metadata was not part of every result boundary | One composition root plus typed context propagation | API/Worker composition and production execution parity tests | External provider live parity still needs credentials/services |

## Canonical behavior

The runtime remains:

```text
AnalysisRequest
  -> one production composition root
  -> profile-aware collection
  -> RepositoryFacts
  -> six analyzers
  -> CategoryResult[]
  -> unchanged ScoreEngineV1
  -> persistence/API
```

`PUBLIC` is backward-compatible as the default request profile. It may use
Git, Vale, PyDriller, SonarQube, git-sizer and TODO-history according to their
capabilities, but it does not use owner-authorized SourceCraft Issues, CI/CD or
AppSec data. `OWNER_EXTENDED` uses the same analyzers and formula with the
additional authorized facts; it is not a second scoring engine.

## AppSec state semantics

| State | Security result | Coverage/confidence |
| --- | --- | --- |
| `NO_SCAN` | inconclusive, no score | 0 / 0 |
| `FINISHED_ZERO_FINDINGS` | numeric score, normally 100 before any frozen caps | 1 / 1 |
| `FINISHED_WITH_FINDINGS` | numeric severity result | 1 / 1 |
| `FAILED` | inconclusive, no fabricated score | 0 / 0 |
| `UNAVAILABLE` | skipped/unavailable | 0 / 0 |
| `PARTIAL` | numeric result only from observed facts, marked partial | 0.5 / 0.5 |

The three-stage SourceCraft chain remains `/v1/scans` → `/v1/defect-groups` →
`/v1/findings`. Raw payloads and credentials do not cross the adapter boundary.

## Frozen behavior and regression gates

- `src/repo_health/scoring/v1.py` and `calibration_v2.py` are unchanged.
- Existing golden/parity fixtures remain the arithmetic source of truth.
- Activity formula inputs and contributor counts remain unchanged; new identity
  fields are provenance/uncertainty metadata only.
- API and Worker use the same collector/analyzer registry and differ only by
  executor mode.
- No Recommendation Engine, UI, merge, push or schema migration is included.

The implementation gates for this branch are:

```text
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q src tests
uv lock --check
uv run pip check
git diff --check
```

The current command results are recorded below; environment-only provider
limitations remain explicit rather than being treated as fabricated success.

## Current verification evidence

| Gate | Result |
| --- | --- |
| `uv run pytest -q` | PASS — 142 passed, 1 existing Starlette/httpx deprecation warning |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS — 113 files formatted |
| `uv run python -m compileall -q src tests scripts` | PASS |
| `uv sync --locked` / `uv lock --check` | PASS |
| `uv pip check` | PASS — 34 packages compatible |
| `uv build` | PASS — sdist and wheel built |
| `scripts/verify_contracts.py --all` | PASS — imports, six-analyzer registry and fact contracts |
| `scripts/verify_production_composition.py` | PASS — one composition root and explicit degraded capabilities |
| `scripts/verify_parity.py --categories all --execution local --execution worker --legacy-replay --fail-on-unmapped` | PASS — category, legacy replay and execution parity |
| `git diff --check` | PASS |
| frozen score files diff | PASS — no diff in `scoring/v1.py` or `scoring/calibration_v2.py` |

The live provider limitations already documented in the external readiness
report remain environment limitations, not hardening failures: a full live
owner-extended SourceCraft run requires authorized SourceCraft access, and
optional Vale/git-sizer/SonarQube capabilities depend on their configured
binary/service. Their unavailable paths are covered by explicit tests and do
not fabricate facts or numeric scores.
