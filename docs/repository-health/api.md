# API reference

[← Previous](architecture.md) · [Back to README](../../README.md) · [Next →](testing.md)

API и CLI читают один persisted canonical projection. Запрос не пересчитывает
score на лету и не скрывает проблемы качества данных.

## Endpoints

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/health` | liveness/readiness сервера |
| `GET` | `/api/repos/{repo_id}/health/canonical` | detail одного репозитория |
| `GET` | `/api/health/ranking` | public ranking с фильтрами и facets |
| `GET` | `/api/health/ranking/compare` | сравнение максимум четырёх eligible rows |
| `GET` | `/api/health/ranking/trend` | bounded history максимум восьми репозиториев |

## Canonical report

```bash
curl "http://127.0.0.1:7337/api/repos/repo-a/health/canonical?include_evidence=false"
```

Поддерживаемые фильтры: `snapshot`, `scope`, `dimension`, `status`, `severity`,
`subject`, `window`, `include_evidence`. Важные поля ответа:

```json
{
  "snapshot": {"id": "snapshot-1", "is_stale": false},
  "score_projection": {
    "overall_score": 82.4,
    "dimensions": {"code": 86.0, "security": 91.0, "tests": null},
    "breakdown": [],
    "evidence_coverage": 0.78,
    "status": "warn",
    "limitations": []
  },
  "recommendations": [],
  "limitations": []
}
```

`breakdown`, `recommendations` и `limitations` в примере сокращены. Клиент
должен проверять `status`, `is_stale` и `overall_score == null`, а не считать
отсутствующее значение нулём.

## Public ranking

```bash
curl "http://127.0.0.1:7337/api/health/ranking?limit=20&band=good&language=python"
```

Фильтры: `page`, `limit` (1–100), `band`, `dimension`, `language`, `status`,
`stale`, `eligible`. По умолчанию `eligible=true`. Для диагностики:

```bash
curl "http://127.0.0.1:7337/api/health/ranking?include_ineligible=true&limit=100"
```

Строка содержит `repository_id`, `name`, `url`, `overall_score`, `band`,
`grade`, `dimensions`, `languages`, `confidence`, `coverage`,
`evidence_coverage`, `analyzed_at`, `stale`, `eligible` и
`eligibility_reason`. В ней намеренно нет локального пути или raw evidence.

## Compare и trend

```bash
curl "http://127.0.0.1:7337/api/health/ranking/compare?repo_ids=repo-a,repo-b"
curl "http://127.0.0.1:7337/api/health/ranking/trend?repo_ids=repo-a,repo-b&limit=12"
```

`compare` принимает до четырёх ID и возвращает dimension matrix плюс список
`score_config_digests`. `trend` принимает до восьми ID и ограничивает число
точек `limit` от 1 до 50. Превышение лимита отмечается полем `truncated`, а не
молча меняет policy score.

## CLI и MCP parity

```bash
uv run repowise health . --format json --health-mode full --explain
uv run repowise health . --trend
uv run repowise health-batch --all --concurrency 2 --resume
```

CLI и MCP используют те же persisted canonical rows. MCP `get_health` может
фильтровать `snapshot_id`, `dimension`, `status`, `severity`, `subject`,
`window` и `include_evidence`. Если нужно объяснение конкретной цифры, сначала
проверьте `score_config_digest`, затем `breakdown` и limitations.

## Подтверждение контракта

| Поверхность | Код | Тест |
| --- | --- | --- |
| canonical REST | [`canonical_routes.py`](../../packages/server/src/repowise/server/routers/code_health/canonical_routes.py) | [`test_health_canonical_score.py`](../../tests/unit/server/test_health_canonical_score.py) |
| ranking REST | [`public_health.py`](../../packages/server/src/repowise/server/routers/public_health.py) | [`test_public_health_compare.py`](../../tests/unit/server/test_public_health_compare.py) |
| CLI | `packages/cli/src/repowise/cli/commands/health_cmd` | [`test_health_canonical_contract.py`](../../tests/unit/cli/test_health_canonical_contract.py) |
| browser ranking | `packages/web/src/components/health-ranking` | [`health-ranking.spec.ts`](../../tests/e2e/health-ranking.spec.ts) |

## See Also

- [Scoring](scoring.md) — что означает каждое поле результата.
- [Architecture](architecture.md) — откуда берётся persisted projection.
- [Testing](testing.md) — как проверить API и UI.
