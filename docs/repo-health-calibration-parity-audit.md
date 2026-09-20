# Repo Health calibration-v2 → production parity audit

Дата аудита: 2026-09-20. Репозиторий: `artem03102006/codex-external-audit-public-20260916`.

Это отдельный audit после внедрения calibration-v2 policy в production analyzers.
Глобальная формула Score Engine v1, веса верхнего уровня и security caps в рамках
аудита не менялись.

## Итог

Все шесть категорий используют одну и ту же зафиксированную policy boundary между
calibration и production. Для четырёх категорий численное значение совпало с
calibration target artifact с допуском `1e-6`. Issues корректно публикует `score=null`
при sample size 1. Security и Code Health проверены по production-normalized facts,
потому что live input availability отличается от calibration запуска.

| Категория | Reference | Production | Delta | Результат | Причина возможного отличия входа |
|---|---:|---:|---:|---|---|
| Documentation | 39.936842 | 39.936842 | `+0.0000001` | PASS | Нет |
| Activity | 66.239175 | 66.239175 | `-0.0000003` | PASS | Нет; одинаковый `as_of` |
| Issues | `null` | `null` | — | PASS | 1 issue ниже minimum sample |
| CI/CD | 75.328947 | 75.328947 | `+0.0000004` | PASS | Нет; trend unavailable reweighted |
| Security | 90.000000 | 90.000000 | `0` | PASS | Calibration AppSec был unavailable, live AppSec measured |
| Code Health | 80.000000 | 80.000000 | `0` | PASS | Live SonarQube unavailable; применён partial-facts policy |

Машиночитаемый результат: [`spikes/scoring/parity-v2/audit.json`](../spikes/scoring/parity-v2/audit.json).

## Что именно исправлено

В `CodeHealthAnalyzer` была найдена реальная причина остаточного расхождения:
при `SonarQube=UNAVAILABLE`, но при наличии git-sizer/TODO facts, analyzer сначала
считал нормализованный score, а затем заменял его legacy baseline score. Это могло
скрывать partial coverage и нарушало calibration-v2 boundary.

Теперь:

- доступные компоненты reweight-ятся по eligible weights;
- confidence применяется один раз к нормализованному raw score;
- `PARTIAL` получает существующий локальный cap `80`;
- baseline score остаётся observability-only и не подменяет новый aggregate;
- legacy baseline сохраняется только в полном fallback, когда usable supplemental
  facts отсутствуют;
- null Sonar complexity/maintainability/duplication не превращаются в healthy `100`.

Для live fixture итоговый Code Health:

- SonarQube: `UNAVAILABLE`;
- git-sizer: `MEASURED`;
- Git-history/TODO: `PARTIAL`;
- eligible components: `git_structure=99.127025`, `todo_debt=100`;
- eligible weight: `0.20` из `1.00`;
- raw score: `99.5635125`;
- confidence: `0.825`;
- partial cap: `80`;
- final category score: `80`, public status `WARN`, facts status `PARTIAL`;
- coverage: `0.6666667`.

## Live normalized facts

### Documentation

Vale v3.22.0 обработал 5 documentation files, coverage и confidence равны 1.
Обнаружено одно medium finding: `README.md:3`, rule `RepoHealth.Clarity`,
формулировка с `AWS-shaped`. Components: completeness `25`, instructions `0`,
Vale quality `88.8`, readability `51.578947`. Общий score — `39.936842`.

### Activity

PyDriller на default branch получил 7 unique commits, 3 authors, churn `234`,
0 empty commits и 0 merge commits. Existing Git collector уже содержал эти 7
hashes: overlap `7`, new commits `0`, поэтому double counting отсутствует.
При calibration `as_of` score равен `66.239175`. Отдельный replay с as-of
`2026-09-16` дал `69.061954`; это ожидаемая разница recency input, а не формулы.

### Issues

SourceCraft вернул 1 issue и 0 comments; pagination complete, comments endpoint
доступен, но actor metadata и explicit state events отсутствуют. Metrics: open `1`,
closed `0`, unanswered `1`, sample `1`. Numeric score не публикуется: status
`PARTIAL`, coverage `0.7`, confidence `0.525`.

### CI/CD

SourceCraft `/cicd/runs`: 16 records, pagination complete, duplicates `0`.
Statuses: success `11`, failure `5`, cancelled `0`, skipped `0`; success rate
`68.75%`, failure rate `31.25%`. Last run — `SUCCESS`, failure streak `0`.
P50 duration `113.760477s`, P95 `185.1294133s`. Previous window empty, поэтому
trend и retry detection не выдумываются; trend component исключается из local
reweighting. Final score — `75.328947`, public status `WARN` из-за failure-rate
finding.

### Security

SourceCraft AppSec live boundary measured. Обнаружено 1 active finding:
`gitleaks:audit-synthetic-secret` в `secret-fixture.txt:1`; payload и secret value
не записывались. Frozen AppSec policy даёт `90` за один unknown/medium-level penalty.
Global Score Engine применяет неизменённый confirmed-secret cap `40` к overall score.

### Code Health

В текущем live окружении SonarQube server не был доступен, поэтому production не
выдаёт Sonar-derived maintainability/complexity/duplication findings и не
подменяет их baseline. git-sizer и TODO layer продолжили работу; итог обозначен
как partial через facts coverage/confidence.

## Reproducibility

Аудит можно повторить из корня репозитория:

```text
uv run pytest -q tests/unit/health/test_calibration_v2_policy.py tests/unit/health/test_code_health.py tests/unit/health/test_module_attribution.py
uv run python scripts/verify_repo_health_score_v1.py
uv run python spikes/scoring/parity-v2/build_parity_audit.py
```

Полный health-suite после исправления:

```text
uv run pytest -q tests/unit/health
```

В audit artifacts нет PAT, токенов, comment bodies, полных diff или исходных
секретов. `token_logged=false` проверяется как часть generated artifacts.

