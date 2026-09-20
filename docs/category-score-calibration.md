# Repo Health category-score calibration v2

Статус: `RESEARCH COMPLETE / PRODUCTION RELEASE BLOCKED`.

Документ фиксирует второй, исправленный calibration run для шести категорий
Repo Health. Это кандидатная методика и экспериментальные результаты. Production
Score Engine в этом исследовании не изменялся.

Главный вывод: кандидатная top-level модель — hybrid aggregation: weighted
arithmetic mean для объяснимого базового score, evidence-coverage gate для
неполных данных и hard cap для подтверждённого critical security signal.
Кандидатные веса сохраняются как `Documentation 15%`, `Activity 15%`,
`Issues 15%`, `CI/CD 15%`, `Security 20%`, `Code Health 20%`. Они устойчивы на
доступной выборке, но production readiness остаётся `NO`, потому что в real
SourceCraft cohort нет полноценного Security результата и нет ни одного
полного Issues результата, а CI измерен только на одном репозитории.

## 1. Объект и воспроизводимость

Единица наблюдения — нормализованный набор шести `CategoryResult` для одного
репозитория. Использовались только существующие analyzer boundaries:

| Категория | Реальный источник в эксперименте |
|---|---|
| Documentation | Vale adapter и существующие completeness facts |
| Activity | PyDriller adapter на локальном Git checkout |
| Issues | SourceCraft issues/comments collector и текущий CHAOSS/OpenDigger-derived analyzer |
| CI/CD | SourceCraft `/cicd/runs` collector и текущий DORA-derived analyzer |
| Security | SourceCraft AppSec boundary; substitute scanner не использовался |
| Code Health | SonarQube Community Build, git-sizer и существующий Git-history layer |

Экспериментальные файлы:

- [`run_calibration_v2.py`](../spikes/scoring/calibration-v2/run_calibration_v2.py) — воспроизводимый non-production runner;
- [`results.json`](../spikes/scoring/calibration-v2/results.json) — redacted normalized results;
- [`category-distributions.csv`](../spikes/scoring/calibration-v2/category-distributions.csv) — распределения scores и missing-rate;
- [`anchors.csv`](../spikes/scoring/calibration-v2/anchors.csv) — directed counterfactual checks;
- [`repo-health-score-calibration.md`](repo-health-score-calibration.md) — предыдущая v1 calibration и ограничения первого прогона.

Параметры финального run:

- `as_of = 2026-09-20T23:59:59Z`;
- 32 реальных public SourceCraft repositories;
- 15 контролируемых fixtures;
- шесть category weights суммарно 100%;
- category analysis windows — существующие 90-day windows analyzer-ов;
- Git — существующая default-branch policy;
- одинаковые входные facts пересчитываются одной функцией без случайности;
- source code, comment bodies, logs, credentials и secrets в artifact не
  сохранялись;
- контрольные fixtures и Sonar runtime находились во внешнем temporary
  calibration workspace, а не в production runtime.

Полный observational run требует только secrets из environment (значения не
печатать и не передавать CLI arguments):

```powershell
$env:SOURCECRAFT_PAT = "<provided-out-of-band>"
$env:SONAR_TOKEN = "<provided-out-of-band>"
uv run python spikes/scoring/calibration-v2/run_calibration_v2.py
```

Для повторной проверки детерминизма уже сохранённых redacted facts применялся
reuse mode без внешних API/scanner calls:

```powershell
$env:REPO_HEALTH_CALIBRATION_V2_REUSE_OBSERVATIONAL = "1"
$env:REPO_HEALTH_CALIBRATION_V2_REUSE_CONTROLLED = "1"
uv run python spikes/scoring/calibration-v2/run_calibration_v2.py
```

### 1.1. SonarQube live setup

Docker path был проверен, но Docker Desktop daemon в окружении не был доступен.
После диагностики использован официальный standalone Community Build ZIP и
официальный SonarScanner CLI:

- SonarQube Community Build `26.9.0.129388`;
- SonarScanner CLI `8.1.0.6389`;
- server реально поднят на `127.0.0.1:9000`;
- scanner upload и background-task completion прошли;
- Web API metrics получены через `SonarQubeAdapter`;
- admin/calibration tokens не записывались в command line или artifact;
- после run все два временных calibration tokens были отозваны, остаток по
  calibration prefix — `0`.

Это подтверждает работоспособность Code Health boundary, но не превращает
частичные source facts в полную coverage.

## 2. Кандидатная top-level методика

### 2.1. Нормализация category scores

Каждый analyzer обязан вернуть score `c_j ∈ [0,100]` только из своих
фактических metrics. Нормализация выполняется внутри категории:

- Documentation: completeness, instructions, Vale quality и readability;
- Activity: history, cadence, recency, meaningful-activity integrity и author
  breadth;
- Issues: существующий Issues score после minimum-sample policy;
- CI/CD: reliability anchors, failure streak, duration и trend;
- Security: SourceCraft AppSec severity-aware score;
- Code Health: Sonar maintainability/debt/complexity/duplication, TODO-age,
  hotspots и git-sizer structural signals.

Top-level score не пересчитывает эти facts и не подставляет нули за
отсутствующие категории.

### 2.2. Primary formula

Пусть `w_j` — top-level weight, `S` — категории с числовым score и измеренным
или partial фактическим результатом. Тогда базовая часть:

```text
H_arithmetic = Σ(j ∈ S) w_j · c_j / Σ(j ∈ S) w_j
```

Веса:

| Category | `w_j` |
|---|---:|
| Documentation | 0.15 |
| Activity | 0.15 |
| Issues | 0.15 |
| CI/CD | 0.15 |
| Security | 0.20 |
| Code Health | 0.20 |

Denominator renormalizes only over measured categories. Это значит, что
`UNAVAILABLE` не превращается в score `0`, но coverage gate не позволяет
неполной картине выглядеть как полноценный результат.

### 2.3. Diagnostic geometric formula

Для sensitivity comparison записывается, но не является primary UI score:

```text
H_geometric = exp(Σ(j ∈ S) w_j · ln(max(c_j, ε)) / Σ(j ∈ S) w_j)
ε = 10⁻⁶
```

Geometric model полезна как нижний stress-test: она сильнее наказывает одну
очень низкую категорию. Однако `ε`, missing categories и scores около нуля
создают дополнительную методологическую чувствительность, поэтому она не
выбрана primary formula.

### 2.4. Coverage и confidence

Для каждой категории:

```text
q_j = clamp(coverage_j, 0, 1) · clamp(confidence_j, 0, 1)
K = Σ(all j) w_j · q_j / Σ(all j) w_j
```

`K` — это evidence coverage, а не штраф, механически умножаемый на score.
Делать `H · K` было бы трудно интерпретировать: при одинаковом качестве
измеренного кода изменялся бы score из-за внешнего permission/API состояния.
Вместо этого `K` управляет label результата:

| Condition | Public label |
|---|---|
| `K ≥ 0.75` и не менее 5 scored categories | `SCORE` |
| `K ≥ 0.50` и не менее 4 scored categories | `PROVISIONAL_SCORE` |
| иначе | `INSUFFICIENT_DATA` |

Пороговые значения `0.50` и `0.75` — наши calibration candidates, а не
научные константы. В production они должны оставаться versioned policy и
пересматриваться при появлении полноценной AppSec/Issues/CI выборки.

Если label `INSUFFICIENT_DATA`, внутренние `H_arithmetic` и `H_geometric`
можно хранить как diagnostics, но пользовательский numeric Repo Health Score
не должен отображаться как окончательный.

### 2.5. Missing-data semantics

| Status | Значение | В top-level aggregation |
|---|---|---|
| `MEASURED` | источник отработал, facts достаточны | category участвует с `q_j` |
| `NO_ACTIVITY` | отсутствие activity фактически наблюдено | не импутировать; category может дать evidence-based activity result, иначе исключить |
| `NOT_APPLICABLE` | metric не имеет смысла для repo/data model | исключить, `q_j=0` |
| `UNAVAILABLE` | permission, endpoint или dependency недоступны | исключить, `q_j=0`, не score `0` |
| `ERROR` | analyzer/source failed | исключить, `q_j=0`, сохранить error evidence |

`PARTIAL` category с числовым score может участвовать; её confidence/coverage
должны уменьшить `q_j`. `UNAVAILABLE` Security не должен понижать Security
category до нуля и одновременно не должен позволять остальным пяти категориям
представляться полным Repo Health.

### 2.6. Security gates и caps

Выбранная hybrid часть:

```text
H_hybrid = min(H_arithmetic, security_cap)  if confirmed security cap exists
           H_arithmetic                       otherwise
```

Кандидатная policy:

| Security state | Cap |
|---|---:|
| confirmed high | 60 |
| confirmed critical | 40 |
| confirmed exposed secret | 40, с обязательным evidence и remediation state |
| fixed/none | no security cap |

Cap применяется только при подтверждённом AppSec finding. `UNAVAILABLE`,
`ERROR` и отсутствие scan не являются security finding и не запускают cap.
Это формально запрещает Documentation=100 или Code Health=100 полностью
компенсировать подтверждённую critical security problem, но сохраняет
объяснимость: UI показывает и arithmetic score, и причину cap.

Отдельный Code Health hard cap не выбран. Code Health уже имеет вес 20%, а
Sonar/debt/complexity findings должны влиять через category score и evidence.
Без единого universally valid “critical code health” semantics дополнительный
cap создавал бы двойной counting.

## 3. Почему hybrid, а не одна средняя

| Model | Сильная сторона | Нерешённая проблема | Решение |
|---|---|---|---|
| Weighted arithmetic | прозрачный вклад каждой category; легко объяснить deltas и renormalization | полностью компенсаторная | оставить как `H_arithmetic` |
| Weighted geometric | низкая category заметно влияет на итог; stress-test против маскировки | sensitive к `ε`, zero и missing; хуже объясним для пользователя | хранить как diagnostic |
| Hybrid | arithmetic сохраняет объяснимость, cap/gate предотвращают опасную компенсацию и ложную полноту | нужен versioned policy для cap/gates | выбрать как final candidate |

В частности, `Documentation=100` не должна компенсировать `Security=20` с
critical finding: при cap `40` итог не превосходит `40`. Но `Security` с
`UNAVAILABLE` не следует трактовать как `20`; вместо этого score остаётся
provisional/insufficient согласно `K`.

## 4. Category calibration formulas

Эти formulas находятся только в `spikes/scoring/calibration-v2` и не являются
production implementation.

### 4.1. Documentation

```text
D = 0.40 · completeness
  + 0.20 · instructions
  + 0.25 · Vale_quality
  + 0.15 · readability
```

Completeness — наличие README, LICENSE, CONTRIBUTING и CODEOWNERS; instructions
— наличие install/setup/run/build/test/usage signals. Vale penalty зависит от
weighted finding points и document word volume, поэтому одно warning не
уничтожает score большого corpus. Это deliberately сохраняет completeness
checks и не превращает Vale в замену им.

### 4.2. Activity

Используется integrity-aware recency model:

```text
history  = min(1, log1p(commits) / log1p(50))
cadence  = min(1, commits_90d / 8)
recency  = exp(-latest_activity_age_days / 45)
breadth  = min(1, authors_90d / 4)
empty_ratio = empty_commits / max(commits, 1)
integrity = clamp(0.70 · meaningful_ratio
                + 0.30 · (1 - empty_ratio), 0, 1)
raw = 100 · (0.25·history + 0.25·cadence + 0.35·recency + 0.15·breadth)
A = raw · (0.25 + 0.75·integrity)
```

Так 100 empty commits не становятся “здоровой активностью”, а свежий
meaningful history получает преимущество над старой history. Это не reward за
максимальное число commits: volume имеет diminishing returns.

### 4.3. Issues

Существующий Issues analyzer сохраняется. В v2 score допускается только при
`sample_size >= 5` и usable comments/state-events. При sample `1` или полном
отсутствии issues data category остаётся `UNAVAILABLE/PARTIAL`, но не получает
нулевой score. Это сознательно защищает closure/response ratios от малой
выборки.

### 4.4. CI/CD

Основной reliability mapping калибруется anchors:

| Failure rate | Reliability subscore |
|---:|---:|
| 0% | 100 |
| 5% | 95 |
| 10% | 90 |
| 20% | 80 |
| 30% | 70 |
| 50% | 50 |
| 100% | 0 |

Финальная category formula использует `0.75 reliability + 0.15 failure streak
+ 0.05 duration + 0.05 trend`; reliability поэтому доминирует над красивыми
duration/last-run signals. Cancelled/skipped не автоматически считаются
failures. Для production
нужны минимум 5 decisive runs и completed pagination.

### 4.5. Code Health

SonarQube — основной maintainability source. Дополнительные signals —
complexity, duplication, TODO/FIXME age, churn/hotspots и git-sizer. Один
engine не может незаметно перезаписать другой: в category facts сохраняются
engine statuses и confidence, а score считается только по доступным
компонентам с audit evidence.

### 4.6. Security

В real cohort substitute AppSec не использовался. Controlled Security rows —
synthetic boundary facts (`none`, `high`, `critical`, `secret`, `fixed`) без
реальных credentials, secrets или source snippets. Эти строки проверяют cap
semantics, а не наличие production AppSec coverage.

## 5. Calibration results

### 5.1. Размеры и real-data coverage

| Cohort | N | Documentation | Activity | Issues | CI/CD | Security | Code Health |
|---|---:|---:|---:|---:|---:|---:|---:|
| Observational, SourceCraft | 32 | 32 scored | 31 scored, 1 unavailable | 0 scored | 1 scored, 29 unavailable, 2 error | 0 scored, 32 unavailable | 32 partial/measured |
| Controlled | 15 | 15 | 15 | 15 | 15 | 15 synthetic | 15 measured |

Observational distributions:

| Category | N | Median | Mean | Min | Max | Missing rate |
|---|---:|---:|---:|---:|---:|---:|
| Documentation | 32 | 54.095 | 54.198 | 21.460 | 81.062 | 0.0% |
| Activity | 31 | 15.806 | 26.236 | 2.099 | 90.023 | 3.1% |
| Issues | 0 | — | — | — | — | 100.0% |
| CI/CD | 1 | 76.563 | 76.563 | 76.563 | 76.563 | 96.9% |
| Security | 0 | — | — | — | — | 100.0% |
| Code Health | 32 | 71.373 | 71.133 | 44.301 | 100.000 | 0.0% |

Флаг `controlled_full_data=true` в `results.json` подтверждает, что на всех 15
owned fixtures статусы были `Documentation=COMPLETED`, остальные пять категорий
`MEASURED`; для Code Health это одновременно SonarQube, git-sizer и bounded
TODO/FIXME age snapshot, с coverage/confidence `1.0`.

Controlled distributions are not a prevalence estimate. Они предназначены для
directional tests: clean baseline, one controlled degradation, and synthetic
missing-data/cap states.

`category-distributions.csv` дополнительно содержит histogram bins
`0–19`, `20–39`, `40–59`, `60–79`, `80–100` и deterministic
`low_example/medium_example/high_example` для каждой category/cohort. Примеры
из итоговой distribution:

| Category | Low example | Medium example | High example |
|---|---|---|---|
| Documentation | `sourcecraft/sourcecraft` — 21.460 | `therteenten/archive-optiram` — 51.923 | `datalens/datalens` — 81.062 |
| Activity | `nphne-3azqbags/gazprombank-reviews-analyzer` — 2.099 | `sourcecraft/sourcecraft` — 45.983 | `dqdkfa/libmdbx` — 90.023 |
| Issues | `controlled/unresponsive-issues` — 49.479 | `controlled/unresponsive-issues` — 49.479 | `controlled/stale-broken-docs` — 78.095 |
| CI/CD | `controlled/ci-repeated-failures` — 45.333 | `controlled/ci-repeated-failures` — 45.333 | `controlled/unresponsive-issues` — 100.000 |
| Security | `controlled/bad-readme` — 100.000 | `controlled/bad-readme` — 100.000 | `controlled/unresponsive-issues` — 100.000 |
| Code Health | `therteenten/archive-optiram` — 44.301 | `roxblnfk/happy-wife-happy-life` — 50.802 | `d-diukin-centr-to-ru/tesr` — 100.000 |

Для Issues и Security observational examples отсутствуют из-за missing real
data; controlled examples явно помечены `controlled/`. Security severity
variation оценивается отдельно через `security_cap_sensitivity`, потому что
base controlled records intentionally используют `Security=100` и не содержат
реальных credentials/secrets.

В `results.json.category_sensitivity` для каждой category отдельно сохранены
observed range, target-anchor count/pass-rate и min/max absolute delta. Это
отделяет чувствительность category formula от top-level weight sensitivity,
которая приведена ниже.

### 5.2. Directed anchors

Final artifact contains 38 checks, all passed (`38/38`, `100%`):

| Signal | Controlled direction |
|---|---|
| Documentation | bad README, missing instructions and stale docs decrease score |
| Activity | fresh meaningful commits do not decrease; 100 empty commits and 240-day inactivity decrease |
| Issues | unanswered issues decrease; responsive issues do not decrease |
| CI/CD | 30% failures and repeated failures decrease; healthy CI does not decrease |
| Code Health | complexity/duplication and old TODO debt decrease |
| Security/top-level | high/critical/secret caps are respected; unavailable engine does not become zero |
| CI reliability | 0/5/10/20/30/50/100% failure anchors are monotone non-increasing |

Отдельный harness audit был существенен. Первый run давал 54.9% из-за ошибки
экспериментального сравнения: каждая scenario проверялась против всех шести
категорий, хотя менялась только одна. После исправления target mapping,
пересчёта observational facts и повторной записи артефактов получили 38
target-specific checks и 100% pass. Non-target drift больше не маскируется под
ошибку целевого метода.

Основные дельты controlled baseline:

| Scenario | Category | Baseline | Mutated | Delta |
|---|---|---:|---:|---:|
| bad-readme | Documentation | 97.240 | 91.024 | -6.216 |
| missing-run-instructions | Documentation | 97.240 | 96.077 | -1.163 |
| stale-broken-docs | Documentation | 97.240 | 96.357 | -0.883 |
| fresh-meaningful-commits | Activity | 71.416 | 72.233 | +0.816 |
| empty-tiny-commits | Activity | 71.416 | 21.062 | -50.354 |
| inactive-history | Activity | 71.416 | 4.576 | -66.840 |
| unresponsive-issues | Issues | 78.095 | 49.479 | -28.616 |
| ci-30-failures | CI/CD | 100.000 | 63.018 | -36.982 |
| ci-repeated-failures | CI/CD | 100.000 | 45.333 | -54.667 |
| complexity-duplication | Code Health | 94.979 | 56.502 | -38.477 |
| old-todo | Code Health | 94.979 | 63.250 | -31.729 |

### 5.3. Target fixture live result

Для `artem03102006/codex-external-audit-public-20260916` реальный final
calibration result:

| Category | Existing score field | v2 calibration score | Status |
|---|---:|---:|---|
| Documentation | 99.600 | 39.937 | measured |
| Activity | 75.140 | 66.239 | measured |
| Issues | — | — | partial, sample size 1 |
| CI/CD | 81.985 | 76.563 | measured, 16 runs, 31.25% failure |
| Security | — | — | unavailable |
| Code Health | 66.516 | 66.516 | partial, confidence 0.883 |

Sonar snapshot на fixture: server `26.9.0.129388`, `1` issue, `10` measures,
background task `SUCCESS`. CI facts: `16` runs, `11` successful, `5` failed,
success rate `68.75%`, P50 duration `113.76s`, P95 `185.13s`, last terminal
status `SUCCESS`. DORA deployment frequency, lead time, change failure rate and
time to restore — `NOT_APPLICABLE`, потому что обычные CI runs не доказывают
deployment/environment/incident semantics.

Top-level candidate result fixture:

```text
H_arithmetic = 62.636750
H_geometric = 61.020739
H_hybrid     = 62.636750
K            = 0.626667
measured     = 4 / 6
state        = PROVISIONAL_SCORE
```

Это именно provisional result. Security/API absence не превращена в Security=0;
она уменьшила `K` и не позволила выдать full `SCORE`.

## 6. Sensitivity, correlation и anti-gaming checks

### 6.1. Weight sensitivity

| Variant | Max absolute delta | Mean absolute delta | Spearman vs candidate |
|---|---:|---:|---:|
| Candidate 15/15/15/15/20/20 | 0.000 | 0.000 | 1.0000 |
| Equal 1/6 | 5.174 | 1.915 | 0.9917 |
| Maintenance-focused | 6.222 | 3.212 | 0.9882 |
| Security/Code Health 25/25 | 7.761 | 2.859 | 0.9933 |

На этой выборке небольшая перестановка weights не меняет ranking радикально.
Это evidence of local stability, не доказательство универсальности весов.

### 6.2. Cross-category correlations

| Pair | N | Spearman |
|---|---:|---:|
| Activity ~ CI/CD | 16 | 0.0315 |
| Activity ~ Issues | 15 | -0.0794 |
| CI/CD ~ Code Health | 16 | -0.0620 |
| Documentation ~ Code Health | 47 | -0.0307 |

Корреляции близки к нулю, но часть N мала и mixed cohort не является
репрезентативной популяцией. Поэтому значения используются как double-counting
screen, а не как причинное доказательство независимости. Semantic review
остаётся обязательным: например, Activity и Issues могут быть связаны
организационно даже при низкой sample correlation.

### 6.3. Security cap sensitivity

Для controlled synthetic scenarios проверены cap values `30/40/50/60`.
Arithmetic score здорового baseline около `91.009`; при cap результат равен
соответственно `30/40/50/60`. При security `high` arithmetic равен `85.009`,
при `critical` — `75.009`, при `secret` — `71.009`. Для critical и exposed-secret candidate policy
выбирает `40`; для high — `60`. Это даёт заметное влияние critical signal и
не позволяет arithmetic mean обнулить смысл cap.

## 7. Что взято из источников, а что является нашей калибровкой

| Решение | Источник/тип утверждения | Что именно применено |
|---|---|---|
| Normalize → weight → aggregate → sensitivity | [OECD/JRC Handbook](https://doi.org/10.1787/9789264043466-en), research/handbook | структура composite-indicator pipeline, явные missing-data и sensitivity steps |
| Шесть разных dimensions | [Linåker, Papatheocharous, Olsson, OpenSym 2022](https://arxiv.org/abs/2208.01105), research | OSS health — multidimensional construct; не одна activity metric |
| Risk-sensitive checks | [OpenSSF Scorecard](https://github.com/ossf/scorecard), industry practice | explicit check impact и critical security handling; checks/weights не копируются |
| Criticality не равна health | [OpenSSF Criticality Score](https://github.com/ossf/criticality_score), industry practice | project importance не смешивается с quality score |
| Responsiveness/project health dimensions | [CHAOSS](https://chaoss.community), metric definitions | denominator-aware Issues metrics и response time semantics |
| Deployment semantics | [DORA metrics](https://dora.dev/guides/dora-metrics/), industry/research practice | CI runs не подменяют deployments, incidents и restore events |
| Quality dimensions | [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html), standard | maintainability/reliability/usability-like dimensions остаются раздельными |
| Code metrics | [SonarQube metric definitions](https://docs.sonarsource.com/sonarqube-community-build/user-guide/code-metrics/metrics-definition), vendor definitions | semantics LOC, complexity, duplication, debt and maintainability |
| Weights 15/15/15/15/20/20 | наша policy calibration | стартовый ТЗ-ориентир и устойчивость ranking на v2 sample |
| `K` formula | наша implementation policy, informed by OECD/JRC | `q=coverage·confidence`, denominator-preserving gate без `H·K` |
| `K=0.50/0.75`, min 4/5 categories | наша calibration candidate | provisional/full labels; не universal scientific constants |
| Security cap high=60, critical/secret=40 | наша risk policy calibration | controlled synthetic cap sensitivity и non-compensability requirement |
| CI reliability anchors | наша category calibration | 0/5/10/20/30/50/100 points chosen as interpretable response curve |

В частности, ни один перечисленный источник не задаёт наши top-level weights,
K thresholds или security cap numbers. Они должны оставаться versioned
configuration с audit trail.

## 8. Readiness decision

| Category | Ready? | Обоснование |
|---|---|---|
| Documentation | YES | 32 real scores; 3/3 targeted controlled degradation anchors passed; ceiling and Vale-volume behavior visible |
| Activity | YES | 31 real scores; fresh/empty/inactive direction anchors passed; recency and empty-commit penalty observable |
| Issues | NO | controlled semantics pass, но real scored N=0 из-за SourceCraft sample/permissions |
| CI/CD | NO | controlled reliability curve pass, но real scored N=1 и 29 unavailable/2 error |
| Security | NO | real AppSec scored N=0; synthetic cap checks не заменяют AppSec validation |
| Code Health | YES | SonarQube реально отработал на real cohort; все 15 controlled fixtures имеют SonarQube + git-sizer + TODO/FIXME facts со статусом `MEASURED`, coverage/confidence `1.0`; complexity/TODO anchors passed |

Overall top-level readiness: `NO`.

Причина не в том, что formula не работает на controlled data. Причина —
неполная empirical validation для трёх важных data populations: SourceCraft
AppSec, real Issues и broad CI. На target fixture методика честно выдаёт
`PROVISIONAL_SCORE`, что является ожидаемым behavior.

## 9. Псевдокод

```python
WEIGHTS = {
    "Documentation": 0.15,
    "Activity": 0.15,
    "Issues": 0.15,
    "CI/CD": 0.15,
    "Security": 0.20,
    "Code Health": 0.20,
}

MISSING = {"UNAVAILABLE", "ERROR", "NOT_APPLICABLE"}

def repo_health(categories):
    measured = {
        name: result
        for name, result in categories.items()
        if result.category_status not in MISSING
        and result.score is not None
    }

    if not measured:
        return {"score": None, "state": "INSUFFICIENT_DATA", "K": 0.0}

    denominator = sum(WEIGHTS[name] for name in measured)
    arithmetic = sum(
        WEIGHTS[name] * clamp(result.score, 0, 100)
        for name, result in measured.items()
    ) / denominator

    geometric = exp(sum(
        WEIGHTS[name] * log(max(1e-6, result.score))
        for name, result in measured.items()
    ) / denominator)

    K = sum(
        WEIGHTS[name]
        * clamp(result.coverage, 0, 1)
        * clamp(result.confidence, 0, 1)
        for name, result in categories.items()
    ) / sum(WEIGHTS.values())

    cap = security_cap_if_confirmed(categories["Security"])
    hybrid = min(arithmetic, cap) if cap is not None else arithmetic

    if K >= 0.75 and len(measured) >= 5:
        state = "SCORE"
    elif K >= 0.50 and len(measured) >= 4:
        state = "PROVISIONAL_SCORE"
    else:
        state = "INSUFFICIENT_DATA"

    return {
        "score": hybrid if state != "INSUFFICIENT_DATA" else None,
        "state": state,
        "arithmetic": arithmetic,
        "geometric": geometric,
        "K": K,
        "measured_categories": len(measured),
        "security_cap": cap,
    }
```

## 10. Следующий безопасный этап

До изменения production Score Engine необходимо:

1. получить real SourceCraft AppSec permission boundary и повторить Security
   cohort без synthetic substitution;
2. получить real Issues/comments sample минимум из нескольких repositories;
3. расширить real CI cohort и отдельно проверить pagination/error strata;
4. повторить controlled fixtures на нескольких языках и размерах repos;
5. заранее зафиксировать versioned policy revision для weights, K и caps;
6. только после этого сравнить candidate output с текущим Score Engine и
   провести backward-compatible migration test.

До выполнения этих условий Score Engine менять нельзя.
