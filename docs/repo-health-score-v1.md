# Repo Health Score v1

Статус: production policy, версия `repo-health-score-v1`.

Документ фиксирует расчёт верхнего Repo Health Score после миграции шести
категорий. Он не меняет определения отдельных analyzers: каждый analyzer
владеет своими facts, score, status, coverage, confidence и evidence. Score
Engine только нормализует их на общей границе и не обращается к внешним API.

## 1. Входной контракт

На вход подаётся конечный набор `AnalyzerResult`. Engine выбирает не более
одного результата для каждой категории:

| Категория | Production result | Вес |
| --- | --- | ---: |
| Documentation | `vale.documentation` | 0.15 |
| Activity | `chaoss.activity` + PyDriller facts | 0.15 |
| Issues | `chaoss.issues_prs` + SourceCraft facts | 0.15 |
| CI/CD | `cicd.sourcecraft` | 0.15 |
| Security | `sourcecraft.appsec` | 0.20 |
| Code Health | `repowise.health` | 0.20 |

Дублирующие результаты не складываются второй раз. Приоритет имеют canonical
analyzer ids; остальные aliases используются только как fallback. Это
предотвращает double counting, например между SourceCraft Git facts и
PyDriller или между CI и Code Health.

## 2. Формула

Для категории `j`:

```text
q_j = coverage_j * confidence_j
K   = Σ(w_j * q_j) / Σ(w_j)
H   = Σ(w_j * C_j) / Σ(w_j), только по категориям с числовым C_j
```

`C_j` — category score в диапазоне 0–100. Недоступная категория не подставляет
0 в `H`; она исключается из знаменателя `H`, но имеет `q_j=0` в `K`.

`RepoHealthScoreV1` возвращает:

- `score_before_cap` — `H` до critical security policy;
- `score_after_cap` / `overall` — публичный score;
- `category_scores`, `category_statuses`, `category_coverage`,
  `category_confidence`, `category_quality`;
- `contributions`/`breakdown` — вес, score, `q`, weighted points и факт
  исключения из знаменателя;
- `coverage_k`, `applied_caps`, `score_config_digest` и limitations.

## 3. Состояния публикации

Внутренний `K` не является дополнительным штрафом к score. Он используется
как eligibility gate, чтобы один измеренный analyzer не выглядел как полный
health report.

| Условие | `presentation_state` | Публичный score |
| --- | --- | --- |
| не менее 5 числовых категорий и `K >= 0.75` | `SCORE` | `score_after_cap` |
| не менее 4 числовых категорий и `K >= 0.50` | `PROVISIONAL_SCORE` | `score_after_cap` с явной пометкой provisional |
| иначе | `INSUFFICIENT_DATA` | `null`; raw diagnostic может быть сохранён для отладки |

Порог `70%` не используется: это не научная константа. В v1 пороги `0.75`,
`0.50`, 5 и 4 являются versioned policy choices, выбранными по controlled
counterfactual validation. Они должны меняться только через новую policy
version и повторную калибровку.

## 4. Missing data и status mapping

`MEASURED` с числовым score участвует в `H`. `PARTIAL` может участвовать, если
сам analyzer выдал числовой score; его coverage/confidence уменьшает `K`.

Следующие состояния не дают measured zero:

- `UNAVAILABLE` — API, permission, missing executable или источник не доступен;
- `ERROR` — analyzer завершился ошибкой;
- `NOT_APPLICABLE` — определение метрики неприменимо к данным репозитория;
- `NO_ACTIVITY`, `CI_NOT_CONFIGURED`, `NO_RUNS`, `INSUFFICIENT_HISTORY` —
  корректные domain states без достаточной измерительной выборки.

Они исключаются из `H`, имеют `q=0`, попадают в `excluded_categories` и
limitations. Поэтому отсутствие Security API не превращается в Security=0, а
отсутствие CI не награждает репозиторий и не объявляет его нестабильным.

## 5. Issues partial-component policy

Issues analyzer считает внутренний score так:

```text
IssuesScore = Σ(w_i * component_i) / Σ(w_i), только по eligible components
IssuesCoverage = Σ(w_i * availability_i) / Σ(w_i)
```

Компоненты и weights:

| Компонент | Вес | Полный источник |
| --- | ---: | --- |
| responsiveness | 0.30 | human comments, bot filtering |
| resolution | 0.30 | closed timestamps, mature issues |
| backlog health | 0.25 | open/stale/age facts |
| maintenance trend | 0.15 | created/closed time buckets |

`minimum_sample=5`; `minimum_coverage=0.80` используется для полной
responsiveness measurement. Независимые partial components могут участвовать
при `partial_component_min_coverage=0.50`, если их собственный denominator
действительно наблюдаем. Неизмеримый response или reopen signal исключается из
denominator, а не получает zero. Если доступных components недостаточно для
содержательного результата, Issues score остаётся `null`.

Это позволяет реальным SourceCraft facts с counts, close state, backlog и
trend дать `PARTIAL` numeric result, не выдумывая first human response,
reopened semantics или comment completeness.

## 6. CI/CD category

Production CI policy v2:

```text
CI = 0.75 * reliability
   + 0.15 * failure_streak_health
   + 0.05 * duration_health
   + 0.05 * stability_trend
```

Весы нормализуются по доступным компонентам, если trend или duration не
измеримы. Reliability использует зафиксированные failure-rate anchors
`0%=100`, `5%=95`, `10%=90`, `20%=80`, `30%=70`, `50%=50`, `100%=0` с
линейной интерполяцией. Failure streak использует
`100*exp(-streak/3)`. Cancelled/skipped не считаются failure. DORA metrics
не выводятся из обычных CI runs: без настоящих deployment/environment/incident
facts они `NOT_APPLICABLE`.

## 7. Security caps

Security остаётся самостоятельной категорией SourceCraft AppSec. После
расчёта `H` применяются только следующие non-compensatory caps:

| Подтверждённый сигнал | Максимум `score_after_cap` |
| --- | ---: |
| high active finding | 60 |
| critical active finding | 40 |
| active secret finding | 40 |

Fixed/resolved findings cap не создают. Security API unavailable cap не
создаёт. Это формально запрещает Documentation=100 или Code Health=100
компенсировать подтверждённую критическую security проблему, но не делает
любую ошибку транспорта нулевым security score.

## 8. Evidence и воспроизводимость

Одинаковые `AnalyzerResult` и одинаковая policy дают одинаковый score,
breakdown, caps и digest. Engine не сохраняет source code, comments, logs,
secrets или полный внешний payload. Evidence остаётся у analyzer:

- Vale — file/rule/line/match;
- PyDriller — commit/ref/history evidence;
- Issues — issue id/url, age, response/close/stale reason;
- CI — run/workflow id, status, duration, failure/retry relation;
- AppSec — engine/rule/severity/state/file/line;
- Code Health — Sonar component/rule/line, TODO age и git-sizer path/object.

## 9. Calibration status

Research and controlled validation artifacts:

- `docs/repo-health-score-methodology.md` — research, source separation,
  aggregation comparison and sensitivity analysis;
- `docs/final-score-validation.md` — controlled real SourceCraft/AppSec/CI
  verification and limitations;
- `spikes/scoring/calibration-v2/` и `spikes/scoring/final-validation/` —
  reproducible experiments, not production runtime code.

В validation подтверждены: monotonic security caps, no-zero missing behavior,
CI failure direction, AppSec REST boundary, real fixture CI path, deterministic
weighted aggregation и отсутствие double counting в выбранном result set.
Недостающие external strata не маскируются синтетикой: public SourceCraft
permission errors остаются `UNAVAILABLE`, а sparse Issues history — `PARTIAL`
или `INSUFFICIENT_DATA`.

## 10. Migration

Старый `composite.py` не удалён. `compare_score_engines()` возвращает legacy и
v1 рядом, чтобы regression fixtures могли сравнить обе политики. Default
orchestrator/persistence выбирает v1, когда присутствуют как минимум две
распознанные canonical Repo Health category results; это минимальная граница,
защищающая старые одно-анализаторные registry fixtures от случайной смены
контракта. Старые произвольные fixtures остаются на legacy fallback до полного
перехода. Переключение не меняет
global Score Engine, frontend, Vale, PyDriller, Issues, CI/CD или Code Health
definitions.

## 11. Pseudocode

```text
results = select_one_result_per_category(analyzer_results)
for category in six_categories:
    result = results.get(category)
    if result is absent or result.status is missing or result.score is null:
        score[category] = null
        q[category] = 0
    else:
        score[category] = clamp(result.score, 0, 100)
        coverage[category] = clamp(read_coverage(result), 0, 1)
        confidence[category] = clamp(read_confidence(result), 0, 1)
        q[category] = coverage[category] * confidence[category]

K = sum(weight[c] * q[c] for c in six_categories)
H = sum(weight[c] * score[c] for c if score[c] != null) \
    / sum(weight[c] for c if score[c] != null)

state = SCORE if numeric_count >= 5 and K >= .75 else
        PROVISIONAL_SCORE if numeric_count >= 4 and K >= .50 else
        INSUFFICIENT_DATA

if state == INSUFFICIENT_DATA:
    public_score = null
else:
    public_score = min(H, security_cap_if_any)
```
