# Repository Health Analyzer: architecture reference

[← Back to README](../../README.md) · [Repository Health docs](../repository-health/architecture.md)

Это compatibility entry point для старого пути документации. Актуальная
архитектура описана в [Architecture](../repository-health/architecture.md), а
здесь зафиксированы обязательные invariants, которые должны сохраняться при
изменениях.

Analyzer execution теперь имеет neutral compatibility entry point под
`packages/core/src/repowise/core/analysis/analyzer_integration/`. Product
composition, persistence, publication, checkpoint storage и adapter bootstrap
остаются на health edge; старые health integration imports продолжают работать
до отдельного одобренного migration с fixture parity.

## Непереговорные invariants

1. Все product surfaces читают один canonical persisted projection.
2. Итоговый score — `0..100`; legacy `0..10` file/module KPI нельзя подставлять
   вместо `score_projection.overall_score`.
3. Missing dimension не превращается в zero: она остаётся `null` и попадает в
   limitations.
4. Criticality — контекст приоритета, но не компонент health score.
5. Public ranking — отдельный materialized read model и не содержит
   `local_path` или raw evidence.
6. Replay/rescore использует сохранённые raw facts и не вызывает повторный
   сбор Forge/Git/native данных.

## Read-model flow

```text
checkout + ref + as_of + score policy
                  |
                  v
        analyzer results + evidence
                  |
                  v
   raw facts -> normalized facts -> snapshot
                  |
       +----------+-----------+
       v                      v
 canonical detail       ranking projection
 REST / CLI / MCP             |
       |                      v
       +---------------> public ranking UI
```

Derived `band` and `facets` принадлежат ranking projection; это derived band + facets,
а не вторая scoring system. Для текущего контракта no schema migration is introduced:
миграционная граница — `0066`.

Vale prose quality — дополнительный adapter `vale.documentation`, описанный в
[актуальной architecture reference](../repository-health/architecture.md#vale-documentation-quality).
Он не заменяет baseline completeness checks и использует versioned policy в
`config/analyzers/vale/`.

## Evidence in code

| Ответственность | Файл |
| --- | --- |
| score composition and weights | [`composite.py`](../../packages/core/src/repowise/core/analysis/health/composite.py) |
| eligibility, bands and stable ordering | [`ranking_projection.py`](../../packages/core/src/repowise/core/analysis/health/ranking_projection.py) |
| persisted canonical report | [`canonical.py`](../../packages/server/src/repowise/server/routers/code_health/canonical.py) |
| public ranking API | [`public_health.py`](../../packages/server/src/repowise/server/routers/public_health.py) |
| ranking response contract | [`health_ranking.py`](../../packages/server/src/repowise/server/schemas/health_ranking.py) |
| detail UI | [`canonical-summary.tsx`](../../packages/web/src/components/code-health/canonical-summary.tsx) |
| ranking UI | [`ranking-page.tsx`](../../packages/web/src/components/health-ranking/ranking-page.tsx) |

## Failure isolation

Native subprocesses run through bounded adapters with timeout, output caps and
redacted diagnostics. A missing capability becomes `skipped`, insufficient data
becomes `inconclusive`, and a failed parser/process becomes `error`; unrelated
analyzers can still contribute evidence. Operational caps and source commits
are configured in `config/analyzers/` and checked against `vendor/SOURCES.lock`.

Recovery command: `make health-replay`. It rebuilds projections from committed
snapshots; raw facts must not be recollected just to repair a UI projection.
Полный composition gate — `uv run python scripts/verify_health_stack.py --full`.

## See Also

- [Architecture](../repository-health/architecture.md) — полная схема с границами слоёв.
- [API](../repository-health/api.md) — публичные response contracts.
- [Native tools](../reference/NATIVE_TOOLS.md) — provenance и pinned sources.
