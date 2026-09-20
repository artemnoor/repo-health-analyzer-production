# Testing and release evidence

[← Previous](api.md) · [Back to README](../../README.md)

Документация считается подтверждённой только вместе с исполняемыми checks.
Ниже разделены быстрый source-level gate, web contract, browser flow и
platform-dependent native/provenance gate.

## Analyzer integration extraction

Нейтральный kernel проверяется отдельно от health bootstrap. В acceptance
набор входят contract golden round-trip, свежий interpreter import guard,
fake registry/planner, cache hit/miss/corruption/policy, process isolation and
timeout kill, runner validation/retry, finding merge, lifecycle ordering and
concurrency, checkpoint/resume replay semantics, adapter compatibility и
full 17-id registration matrix. Параметры native tools берутся из
`config/analyzers/native-tools.yaml`.

Fixture comparator нормализует только elapsed duration и generated timestamps.
Status, отсутствующий score, evidence/provenance, limitations, diagnostics,
cache hit и ordering нормализовать нельзя. До прохождения parity gates старый
RepoWise health path, adapter modules и bootstrap не retired и не удаляются.

Pipeline `init/update` checkpoint/resume tests остаются отдельным regression
контуром: наличие health cursor не меняет их prefix-skip и output rehydration
семантику.

### Known baseline warning: missing coverage module

The immutable pre-modularization baseline does not contain
`repowise.core.analysis.health.coverage`. This is a pre-existing baseline
limitation, not an extraction change, and is recorded as WARN/out-of-scope.
Compatibility, parity, and CLI/pipeline/init/update regressions that import the
legacy health package install the established in-memory test-only shim before
collection; the shim is asserted absent from both the working tree and the
baseline and never creates a production file. Neutral-core, boundary, process,
and normal focused tests remain separate evidence and run without that shim.

### Vale adapter gate

Vale-specific unit/integration coverage находится в
[`test_vale_adapter.py`](../../tests/unit/health/test_vale_adapter.py). Она
проверяет parsing diagnostics/metrics, deterministic discovery and batching,
clean documentation, warning/error findings, valid threshold exit, missing
Vale, malformed JSON, timeout, no-documentation denominator, replay/cache
identity, public evidence redaction, registration и composition with the
existing docs source.

The live fixture verification uses the official Vale v3.22.0 binary from the
spike and the checked-in policy, not Vale source embedded in the package. On
`artem03102006/codex-external-audit-public-20260916` it found:

- 4 supported files analyzed, coverage `1.0`, metrics coverage `1.0`;
- one real finding: `RepoHealth.Clarity`, `README.md:3`, severity `warning`,
  matching `AWS-shaped`;
- Vale quality `99.5`, result status `warn`;
- existing RepoHealth baseline: overall `33`, docs category `5/15`;
- normalized composition docs dimension: `45.0` before Vale and `49.9545`
  after Vale; composed overall changed from `31.1905` to `31.5444`.

The before/after comparison demonstrates that Vale is additive: baseline
completeness findings remain present, while the single prose finding changes
only the bounded docs-quality contribution.

## Быстрый gate

```bash
uv run python scripts/verify_health_docs.py
uv run python scripts/verify_health_completion.py --run-tests
```

`verify_health_docs.py` проверяет documented paths, workflow jobs, Make targets,
`vendor/SOURCES.lock` commits и ключевые score/ranking markers. Completion gate
проверяет source surface и запускает focused health tests.

## Python contract

Команда, использовавшаяся для текущего canonical/ranking change:

```bash
uv run pytest -q \
  tests/unit/health \
  tests/unit/persistence/test_health_ranking_projection.py \
  tests/unit/server/test_health_canonical_score.py \
  tests/unit/server/mcp/test_health_canonical_projection.py \
  tests/unit/server/test_health_ranking.py \
  tests/unit/server/test_public_health_compare.py \
  tests/unit/cli/test_health_canonical_contract.py \
  tests/integration/test_health_composite_score.py \
  tests/integration/test_health_completion_matrix.py \
  tests/integration/test_health_replay_rescore.py \
  tests/integration/test_public_health_ranking.py \
  tests/integration/test_health_batch_resume.py
```

Последнее подтверждение на рабочей ветке: **1683 passed, 1 skipped, 1
warning**. Completion gate дал **78 passed**.

## Web и browser

```bash
npm --workspace packages/web run test
npm --workspace packages/web run type-check
npm --workspace packages/web run test:e2e -- \
  --project=chromium tests/e2e/health-ranking.spec.ts
```

Последнее подтверждение: **12 web tests**, **9 shared UI tests**, type-check
для web/UI/types/api-client и **2 ranking E2E tests** прошли. Browser сценарий
проверяет score bands, filters, compare drawer, trend, safe encoded IDs, API
error state, narrow viewport и keyboard close.

## Persistence и migration

Для временной SQLite базы проверен upgrade path `0001 → 0066`. Важная граница
совместимости — migration head `0066`; её нельзя обходить downgrade-ом при
обычном откате UI/API.

Replay/rescore подтверждает три invariants:

- повторный replay не дублирует raw facts;
- rescore меняет projection, но не recollects raw facts;
- CLI, REST, MCP и UI получают один canonical score.

## Полный composition gate

На Linux/CI доступны:

```bash
make vendor-verify
make build-native
make test-native
make test-composition
make health-replay
```

Единая redacted команда:

```bash
uv run python scripts/verify_health_stack.py --full
```

На Windows vendor/native gate может быть platform-blocked из-за отсутствия
GNU Make, Go, Rust или Java toolchain. Это не следует считать pass: blocker
должен остаться видимым в `health-stack.log`. Windows-equivalent для source
contract — `uv run python scripts/verify_health_completion.py --run-tests`.

## Известные ограничения QA

- локальная пустая база даёт корректный `200` с пустым ranking, но не может
  показать detail без persisted repository snapshot;
- native/vendor provenance проверяет pinned внешние источники отдельным gate;
- публичная eligibility зависит от freshness и evidence coverage, поэтому
  один и тот же репозиторий может исчезнуть из default ranking без потери raw
  facts;
- UI показывает recommendation и limitation только в пределах данных,
  реально сохранённых snapshot.

## Evidence map

| Область | Основной источник |
| --- | --- |
| score invariants | [`tests/unit/health/test_score_invariants.py`](../../tests/unit/health/test_score_invariants.py) |
| canonical contract | [`tests/unit/cli/test_health_canonical_contract.py`](../../tests/unit/cli/test_health_canonical_contract.py) |
| ranking eligibility | [`tests/unit/server/test_health_ranking.py`](../../tests/unit/server/test_health_ranking.py) |
| public API | [`tests/unit/server/test_public_health_compare.py`](../../tests/unit/server/test_public_health_compare.py) |
| replay/rescore | [`tests/integration/test_health_replay_rescore.py`](../../tests/integration/test_health_replay_rescore.py) |
| analyzer kernel boundary | [`tests/unit/health/test_analyzer_integration_core_boundary.py`](../../tests/unit/health/test_analyzer_integration_core_boundary.py) |
| analyzer kernel behavior | [`tests/unit/health/test_analyzer_integration_core.py`](../../tests/unit/health/test_analyzer_integration_core.py) |
| adapter/bootstrap compatibility | [`tests/unit/health/test_analyzer_integration_compatibility.py`](../../tests/unit/health/test_analyzer_integration_compatibility.py) |
| browser flow | [`tests/e2e/health-ranking.spec.ts`](../../tests/e2e/health-ranking.spec.ts) |

## See Also

- [Getting started](getting-started.md) — повторить локальный сценарий.
- [API](api.md) — surface, которую проверяют эти тесты.
- [Architecture](architecture.md) — почему replay и public projection разделены.
