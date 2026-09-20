# Architecture

[← Previous](scoring.md) · [Back to README](../../README.md) · [Next →](api.md)

## Общая схема

```text
repository checkout / Git ref / as_of / score policy
                         |
                         v
                   AnalyzerContext
                         |
                         v
       local analyzers + native adapters + Forge adapters
                         |
                         v
              AnalyzerResult + evidence + status
                         |
                         v
       raw facts -> normalized facts -> immutable snapshot
                         |
              +----------+-----------+
              v                      v
       canonical projection    ranking projection
       REST / CLI / MCP               |
              |                       v
              +---------------> ranking UI
```

Проект использует текущий Python namespace `repowise`, но health product
contract находится в собственных слоях composition, persistence, API и UI.
Это важно: названия пакетов не являются пользовательской моделью продукта.

## Neutral analyzer integration core

`repowise.core.analysis.analyzer_integration` — нейтральное execution kernel.
Он владеет только contracts, deterministic registry/planner, result validation,
runner, cache/process boundaries, lifecycle и finding merge. Его initializer не
регистрирует analyzers и не импортирует health edge, adapters, RepoWise,
vendor, ingestion, GitIndexer, persistence/SQLAlchemy или public models.

```text
neutral core: contracts -> plan -> run -> lifecycle -> generic outcome
       ^              ports: context / score / persistence / publish / checkpoint
       |
health edge: explicit adapter bootstrap + compose_health_score + JobStore + read models
```

Score остаётся opaque в kernel: `compose_health_score` инжектируется health
edge, как и persistence, publication, context collection и checkpoint adapter.
Старые `health.integrations.*` imports являются compatibility facades; старые
adapters и их bootstrap остаются operational и не удаляются.

## Слои и владельцы

| Слой | Владелец | Ответственность |
| --- | --- | --- |
| Collection | health analyzers/adapters | собрать локальные, native и Forge facts |
| Normalization | `AnalyzerResult` contracts | привести source results к status, score, metrics, evidence и limitations |
| Composition | `composite.py` | посчитать versioned `0..100` projection |
| Persistence | health snapshot/score projection tables | сохранить raw facts, findings, recommendations и immutable snapshot |
| Canonical read model | `canonical.py` | отдать тот же persisted report CLI/REST/MCP/UI |
| Public read model | ranking CRUD + `public_health.py` | отфильтровать, отсортировать и безопасно публиковать eligible rows |
| Presentation | Next.js ranking/detail components | показать score, breakdown, states, recommendations и trend |

## Vale documentation quality

Vale подключён как дополнительный source для `docs`, а не как замена
`repohealth.baseline`. Поток выглядит так:

```text
AnalyzerContext / inventory
          |
          v
ValeAdapter
  - выбирает документационные файлы
  - вызывает официальный Vale CLI через ProcessExecutor
  - читает JSON diagnostics и ls-metrics
  - нормализует их в ValeFacts
          |
          v
AnalyzerResult(vale.documentation, dimension=docs)
          |
          +--> compose_health_score()
```

Adapter не передаёт orchestration/composition layer ни raw Vale JSON, ни CLI
arguments. Версионируемая policy и стили находятся в
`config/analyzers/vale.yaml` и `config/analyzers/vale/`:

- `Terminology.yml` проверяет canonical product name `SourceCraft`;
- `Clarity.yml` проверяет узкий сигнал неопределённой формулировки
  `AWS-shaped`;
- `Readability.yml` задаёт консервативный built-in readability threshold.

Официальный бинарник Vale не встраивается в Python package. Adapter принимает
явный `AnalyzerContext.tool_paths["vale"]`, ищет provisioned `bin/vale(.exe)` и
только затем использует PATH. Все запуски проходят через bounded process
boundary с timeout и output cap.

Документационная полнота остаётся ответственностью существующих checks README,
LICENSE, CONTRIBUTING, CODEOWNERS и инструкций запуска/build/test. Vale измеряет
качество prose и не делает отсутствие документации похожим на плохой текст.

## Persistence и replay

Порядок сохранения: source runs → raw facts → normalized facts → metric values
и finding evidence → aggregates/recommendations → immutable
`RepositoryHealthSnapshot`. Повторный запуск с теми же repository, HEAD,
`as_of_ts` и config digest должен быть идемпотентным.

`rescore` читает уже сохранённые raw facts и меняет projection/aggregate. Он не
вызывает Forge, Git или native collection заново. Это позволяет проверить новую
политику score без потери воспроизводимости исходного измерения.

## Public ranking policy

Ranking хранит не raw report, а безопасную headline projection: repository name,
public URL, score, band/grade, dimensions, freshness, evidence и score delta.
Строка eligible только если:

1. repository visibility — `public`;
2. score finite и доступен;
3. snapshot mode — `fast` или `full`;
4. snapshot не stale (по умолчанию максимум 30 дней);
5. evidence coverage ≥ 0.5.

Сортировка детерминирована: score → evidence coverage → freshness →
case-folded name → repository ID. `include_ineligible=true` показывает причины
отбраковки для диагностики, но не возвращает `local_path` и raw payload refs.

## Изоляция ошибок

Каждый analyzer возвращает статус отдельно. Missing capability — `skipped`,
insufficient denominator — `inconclusive`, parser/process failure — `error`.
Остальные результаты сохраняются и могут дать частичный report. Native runner
ограничивает argv, environment, timeout, stdout/stderr и redacted diagnostics.
`skipped`, `inconclusive` и `error` не сводятся к score `0`; evidence,
provenance, limitations, diagnostics и raw payload references проходят через
neutral contracts без потери порядка.

Health resume cursor — маркер replay job и не доказательство rehydrated output:
health orchestrator сохраняет текущую replay semantics. Отдельный pipeline
resume может пропускать prefix только при наличии собственной durable output
rehydration.

## Evidence in repository

| Контракт | Файл |
| --- | --- |
| composition | [`composite.py`](../../packages/core/src/repowise/core/analysis/health/composite.py) |
| ranking eligibility | [`ranking_projection.py`](../../packages/core/src/repowise/core/analysis/health/ranking_projection.py) |
| canonical API | [`canonical_routes.py`](../../packages/server/src/repowise/server/routers/code_health/canonical_routes.py) |
| public API | [`public_health.py`](../../packages/server/src/repowise/server/routers/public_health.py) |
| public schema | [`health_ranking.py`](../../packages/server/src/repowise/server/schemas/health_ranking.py) |
| migrations | [`packages/core/alembic/versions`](../../packages/core/alembic/versions) |

## See Also

- [API](api.md) — endpoints поверх read models.
- [Scoring](scoring.md) — формула и границы данных.
- [Testing](testing.md) — replay, migration и browser evidence.
