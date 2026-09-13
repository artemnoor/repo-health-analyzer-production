# Getting started

[← Back to README](../../README.md) · [Next →](scoring.md)

## Что получится

После этого сценария у вас будет:

1. сохранённый health snapshot для одного checkout;
2. объяснимый canonical report с score и рекомендациями;
3. API, из которого можно получить detail или публичный ranking;
4. web-страница `/ranking` для eligible public repositories.

Сервис анализирует локальный checkout. Для открытого GitHub/GitLab репозитория
сначала клонируйте его или подключите существующий checkout, затем запускайте
тот же health pipeline. Данные внешнего Forge обогащают report только если
провайдер и его разрешения доступны; отсутствие провайдера показывается как
ограничение, а не скрытая победа.

## Установка

Из корня проекта:

```bash
uv sync --all-packages --all-extras
npm ci
```

Проверить окружение:

```bash
uv run repowise --version
node --version
git --version
```

Минимум: Python 3.11+, Node.js 20+ и Git.

## Анализ одного репозитория

Детерминированный fixture из проекта — безопасный первый запуск:

```bash
uv run repowise health tests/fixtures/health/replay_repo \
  --no-workspace --format json --health-mode full \
  --as-of 2026-01-01T00:00:00Z --explain
```

Для обычного checkout:

```bash
uv run repowise health . --no-workspace --format json \
  --health-mode full --explain
```

Команда печатает JSON в stdout; при необходимости сохраните его в файл уже
после создания собственного каталога для artifacts.

Флаги означают:

- `--health-mode full` — полный набор доступных анализаторов;
- `--as-of` — фиксирует временную границу для replay;
- `--explain` — добавляет status, evidence coverage и limitations;
- `--no-workspace` — не ищет соседние репозитории.

`fast` удобен для локальной итерации, `offline` отключает сетевой сбор,
`diff` ограничивает scope изменениями, `backfill` предназначен для истории.

## Запуск API и web

В одном терминале:

```bash
uv run repowise serve --no-ui --host 127.0.0.1 --port 7337
```

Во втором:

```bash
npm --workspace packages/web run dev
```

Проверки:

```bash
curl "http://127.0.0.1:7337/health"
curl "http://127.0.0.1:7337/api/health/ranking?limit=20"
```

Откройте `http://127.0.0.1:3000/ranking`. Пустой список при пустой базе —
валидный результат: рейтинг не создаёт фальшивые rows без persisted snapshots.

## Анализ нескольких репозиториев

```bash
uv run repowise health-batch --all --concurrency 2 --resume
```

`health-batch` планирует анализ workspace, ограничивает concurrency и умеет
продолжать незавершённую фазу. В публичную выдачу попадают только строки,
прошедшие eligibility policy; приватные или stale snapshots остаются доступными
для диагностики через `include_ineligible=true`.

## Как читать detail

В canonical report смотрите в таком порядке:

1. `score_projection.overall_score` — итог от 0 до 100;
2. `dimensions` и `breakdown` — что именно повлияло на итог;
3. `evidence_coverage`, `status`, `limitations` — насколько результату можно доверять;
4. `recommendations` — действия с remediation и безопасными locations.

Детальная UI-панель также показывает stale/partial/unavailable/error состояния
вместо того, чтобы превращать их в зелёный score.

## Подтверждение реализации

| Сценарий | Код/тест |
| --- | --- |
| canonical detail | [`canonical_routes.py`](../../packages/server/src/repowise/server/routers/code_health/canonical_routes.py) и [`test_health_canonical_score.py`](../../tests/unit/server/test_health_canonical_score.py) |
| public ranking | [`public_health.py`](../../packages/server/src/repowise/server/routers/public_health.py) и [`test_public_health_compare.py`](../../tests/unit/server/test_public_health_compare.py) |
| web ranking | [`page.tsx`](../../packages/web/src/app/ranking/page.tsx) и [`health-ranking.spec.ts`](../../tests/e2e/health-ranking.spec.ts) |

## See Also

- [Scoring](scoring.md) — формула и семантика score.
- [API](api.md) — endpoints и query parameters.
- [Testing](testing.md) — команды проверки.
