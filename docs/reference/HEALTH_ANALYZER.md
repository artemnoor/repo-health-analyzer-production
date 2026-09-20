# Health Analyzer reference

[← Back to README](../../README.md) · [Repository Health docs](../repository-health/getting-started.md)

Это compatibility entry point для существующих ссылок на health reference.
Полное описание продукта разделено на пять страниц в
[`docs/repository-health/`](../repository-health/getting-started.md), чтобы не
смешивать пользовательский сценарий, формулу score и внутренний pipeline.

## Канонический контракт

| Контракт | Источник истины |
| --- | --- |
| Repository score | `score_projection.overall_score`, `0..100` |
| Dimensions | `code`, `history`, `tests`, `dependencies`, `security`, `delivery`, `community`, `docs` |
| Public ranking | materialized public projection, а не raw snapshot |
| Detail recommendations | persisted recommendations с remediation, severity и evidence |
| Missing data | `null`/status/limitations, а не искусственный ноль |

`0` is a measured score. `null` means that a usable canonical projection is
unavailable. `skipped`, `inconclusive`, `warn` and `error` remain visible data
quality states. Критичность используется для приоритета рекомендаций и не
вычитается из health score.

## Ranking bands

| Band | Boundary |
| --- | --- |
| Excellent | `90..100` |
| Good | `80..<90` |
| Fair | `70..<80` |
| Weak | `60..<70` |
| Critical | `0..<60` |
| Unknown | score unavailable or non-finite |

Публичная eligibility-политика по умолчанию требует public repository,
`fast`/`full` snapshot, свежесть и evidence coverage не ниже `0.5`.
`include_ineligible=true` включает диагностические строки и причины, но не
открывает `local_path` или raw payload references.

## Команды и endpoints

```bash
uv run repowise health <path> --format json --health-mode full --explain
uv run repowise health-batch --all --concurrency 2 --resume

curl "http://127.0.0.1:7337/api/health/ranking?limit=50"
curl "http://127.0.0.1:7337/api/health/ranking/compare?repo_ids=repo-a,repo-b"
curl "http://127.0.0.1:7337/api/health/ranking/trend?repo_ids=repo-a&limit=12"
curl "http://127.0.0.1:7337/api/repos/repo-a/health/canonical?include_evidence=false"
```

Детали параметров и response shape находятся в [API reference](../repository-health/api.md).
Формула и веса — в [Scoring](../repository-health/scoring.md). Команды проверки —
в [Testing](../repository-health/testing.md).

## Verification checkpoint

Для source-level проверки используйте:

```bash
uv run python scripts/verify_health_docs.py
uv run python scripts/verify_health_completion.py --run-tests
```

Для полного release gate остаются отдельные provenance-проверки:
`make vendor-verify`, `make build-native`, `make test-composition` и
`make health-replay`. Они подтверждают pinned native sources, parser results,
replay deduplication, rescore invariants и canonical projection stability.

На Windows without GNU Make используйте Windows-equivalent команды через `uv`;
platform blocker native gate должен оставаться явным, а не считаться pass.

Миграция `0066` остаётся compatibility boundary: migration head `0066` нельзя
считать заменяемой деталью. При откате UI/API не нужно
заново собирать raw facts: восстановите consumer commit, выполните
`make health-replay` и `make health-completion`, затем перестройте ranking
projection.

### Release checkpoint

| Поле | Что зафиксировать |
| --- | --- |
| Branch and commit | точный release ref и commit ID |
| Migration head | `0066` |
| Source ledger | `vendor/SOURCES.lock` и redacted `vendor-sources.log` |
| Focused contract | `make health-contract` или Windows-equivalent `uv` команда |
| Web contract | web tests, type-check и ranking E2E |
| Native/toolchain | pass либо явный timeout/platform blocker |
| Recovery evidence | replay/completion results и artifact paths |

## See Also

- [Scoring](../repository-health/scoring.md) — как рассчитывается score.
- [Architecture](../repository-health/architecture.md) — pipeline и read models.
- [Testing](../repository-health/testing.md) — подтверждение результата.
- [Issues Analyzer](ISSUES_ANALYZER.md) — SourceCraft issue lifecycle, responsiveness, backlog, and score policy.
- [CI/CD Analyzer](CICD_ANALYZER.md) — SourceCraft runs, reliability, duration, trends, confidence, and DORA applicability.
- [Code Health Analyzer](CODE_HEALTH_ANALYZER.md) — SonarQube Community Build, git-sizer JSON v2, Git-history TODO debt, status mapping, and confidence-adjusted code score.
