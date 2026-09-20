# Repository Health Analyzer

Сервис, который превращает состояние открытого репозитория в объяснимый
**Repo Health Score от 0 до 100**. Он показывает, какие измерения повлияли на
оценку, где есть подтверждённые проблемы и что исправить в первую очередь.

Проект состоит из API/CLI на Python и web-интерфейса на Next.js. Основной
сценарий: проанализировать один checkout репозитория, сохранить подтверждённый
snapshot, открыть детальный отчёт и при необходимости включить репозиторий в
публичный рейтинг.

## Что уже работает

- детальная оценка одного репозитория с score, dimensions, evidence,
  limitations и recommendations;
- единый canonical score `0..100` во всех поверхностях: CLI, REST, MCP и UI;
- публичный рейтинг `/ranking` с фильтрами, band, freshness и evidence coverage;
- сравнение до четырёх репозиториев и история score;
- безопасная публикация: рейтинг не отдаёт `local_path` и raw evidence;
- replay/rescore из сохранённых raw facts без повторного сбора данных.

Скоринг не маскирует отсутствие данных. Измерение без usable evidence остаётся
`null`, а недоступность источника попадает в `limitations`; это отличается от
реального нулевого результата. legacy `0–10` scale остаётся только для старых
file/module KPI и не используется как оценка репозитория.

## Быстрый запуск из исходников

Требования: Python 3.11+, `uv`, Node.js 20+ и Git.

```bash
uv sync --all-packages --all-extras
npm ci

uv run repowise health tests/fixtures/health/replay_repo \
  --no-workspace --format json --health-mode full \
  --as-of 2026-01-01T00:00:00Z --explain
```

Запустить API и web отдельно:

```bash
uv run repowise serve --no-ui --host 127.0.0.1 --port 7337
npm --workspace packages/web run dev
```

После запуска:

- API: `http://127.0.0.1:7337/health`;
- рейтинг: `http://127.0.0.1:3000/ranking`;
- canonical отчёт: `/api/repos/<repo_id>/health/canonical`.

Минимальный API-запрос к рейтингу:

```bash
curl "http://127.0.0.1:7337/api/health/ranking?limit=20&band=good"
```

Пример смысла результата: `82.4/100` — это не среднее старых file KPI, а
`score_projection.overall_score`, вычисленный из доступных измерений. В ответе
также должны быть breakdown, evidence coverage, статус и конкретные remediation.

## Как читать результат

| Часть отчёта | Что означает |
| --- | --- |
| `overall_score` | итоговая оценка репозитория `0..100`; `0` — измеренный результат |
| `dimensions` | оценки code, history, tests, dependencies, security, delivery, community и docs |
| `breakdown` | вклад измерений и источников в итог |
| `evidence_coverage` | насколько результат подтверждён доступными evidence |
| `limitations` | что не удалось измерить и почему |
| `recommendations` | действие, location, severity, remediation и безопасное evidence |

Публичная строка появляется в рейтинге только если репозиторий public, snapshot
свежий, режим анализа rankable и evidence coverage не ниже 0.5. Поэтому
`score = 99` без достаточных подтверждений не становится честным местом в
рейтинге.

## Документация

| Раздел | Содержание |
| --- | --- |
| [Getting started](docs/repository-health/getting-started.md) | анализ одного checkout, API, web и public-repo workflow |
| [Scoring](docs/repository-health/scoring.md) | формула, веса, bands, evidence и рекомендации |
| [Architecture](docs/repository-health/architecture.md) | pipeline, persistence, projections и границы публичных данных |
| [API](docs/repository-health/api.md) | canonical report, ranking, compare и trend |
| [Testing](docs/repository-health/testing.md) | реальные команды проверки, QA evidence и известные ограничения |
| [Documentation hub](docs/README.md) | карта health-документации и legacy-материалов проекта |

Production backend cleanup/readiness:
[architecture](docs/architecture.md), [scoring](docs/scoring.md),
[analyzer boundaries](docs/analyzers/README.md),
[SourceCraft integration](docs/sourcecraft-integration.md),
[deployment](docs/deployment.md) and [development](docs/development.md).

Инженерные compatibility entry points:
[health reference](docs/reference/HEALTH_ANALYZER.md),
[architecture reference](docs/architecture/repository-health.md) и
[native source map](docs/reference/NATIVE_TOOLS.md).

Быстрый focused gate: `make health-contract` или
`uv run python scripts/verify_health_completion.py --run-tests` на Windows.

## Границы продукта

Обязательная часть продукта — детальный health отчёт отдельного репозитория и
простая страница публичного рейтинга. Расширенная часть уже подготовлена
контрактами: compare/trend, facets, eligibility diagnostics, replay/rescore и
versioned score policy. Следующий слой развития — более глубокая аналитика
трендов, richer ingestion для внешних Forge и дополнительные действия по
рекомендациям.

## Лицензия

AGPL-3.0-or-later. См. [LICENSE](LICENSE).
