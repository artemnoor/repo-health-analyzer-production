# Testing and release evidence

[← Previous](api.md) · [Back to README](../../README.md)

Документация считается подтверждённой только вместе с исполняемыми checks.
Ниже разделены быстрый source-level gate, web contract, browser flow и
platform-dependent native/provenance gate.

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
| browser flow | [`tests/e2e/health-ranking.spec.ts`](../../tests/e2e/health-ranking.spec.ts) |

## See Also

- [Getting started](getting-started.md) — повторить локальный сценарий.
- [API](api.md) — surface, которую проверяют эти тесты.
- [Architecture](architecture.md) — почему replay и public projection разделены.
