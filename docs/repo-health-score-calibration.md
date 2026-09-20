# Repo Health Score: эмпирическая калибровка и release gate

Статус документа: `CONDITIONAL / RESEARCH COMPLETE, PRODUCTION RELEASE BLOCKED`.

Этот документ фиксирует воспроизводимую кандидатную методику агрегирования шести
категорий Repo Health Score и результаты первого реального прогона по публичной
выборке SourceCraft. Production Score Engine в рамках этого исследования не
изменялся.

Краткий вывод: модель `weighted arithmetic mean + evidence coverage gate +
critical-security cap` лучше всего соответствует требованиям объяснимости,
частичных данных и существенного влияния критических проблем. Кандидатные веса
15/15/15/15/20/20 устойчивы на доступной выборке по ранжированию, но их нельзя
считать окончательно калиброванными для всех шести категорий: AppSec был
`UNAVAILABLE` у всех 36 успешных запусков, CI был измерен только на одном
fixture, а Issues не получил ни одного полноценного scored результата.

## 1. Объект и воспроизводимость

### 1.1. Что считалось

Единица анализа — один нормализованный набор `CategoryResult` для одного
репозитория. Использовались только уже существующие analyzer boundaries:

| Категория | Экспериментальный источник |
|---|---|
| Documentation | Vale adapter и существующие completeness facts |
| Activity | PyDriller adapter на локальном Git checkout |
| Issues | SourceCraft issues/comments collector и CHAOSS/OpenDigger-derived analyzer |
| CI/CD | SourceCraft `/cicd/runs` collector и DORA-derived analyzer |
| Security | SourceCraft AppSec boundary; substitute scanner не использовался |
| Code Health | текущие Code Health facts, git-sizer и Git-history layer; SonarQube не был подменён другим engine |

Параметры запуска:

- `as_of = 2026-09-20T23:59:59Z`;
- локальные временные окна analyzer-ов — 90 дней, если конкретный analyzer
  поддерживает окно;
- публичный каталог SourceCraft был зафиксирован перед выборкой;
- Git — default branch, полный доступный history, без полного хранения diff;
- никакие токены, source code, comment body или секреты в результаты не
  записывались;
- все сортировки, выборки и округления детерминированы.

Точный список и статусы репозиториев лежат в
[`repos.csv`](../spikes/scoring/calibration/repos.csv), нормализованные результаты
— в [`results.json`](../spikes/scoring/calibration/results.json), sensitivity
matrix — в [`sensitivity.csv`](../spikes/scoring/calibration/sensitivity.csv).

Команда повторного запуска из корня репозитория:

```text
$env:PYTHONPATH = "packages/core/src"
.\.venv\Scripts\python.exe spikes/scoring/calibration/run_calibration.py
```

Runner использует только `SOURCECRAFT_PAT` из environment и никогда не печатает
его значение.

### 1.2. Выборка

В каталог было отобрано 38 репозиториев из заранее определённых страт:

- 5 mature/high-rating;
- 5 самых старых в зафиксированном каталоге;
- 5 самых новых;
- языковые квоты;
- детерминированная hash-выборка;
- отдельный реальный fixture-anchor
  `artem03102006/codex-external-audit-public-20260916`.

Итог:

| Показатель | Значение |
|---|---:|
| Выбрано | 38 |
| Успешно обработано всеми экспериментальными этапами | 36 |
| Clone failures | 2 (`divkit/divkit`, `yurvon/origa`) |
| Различных language labels в успешной выборке | 15 |
| Полностью измеренных шести категорий | 0 |
| Production code changed | нет |
| Score Engine changed | нет |

Два clone failure сохранены как `ERROR`, а не удалены из журнала. Поэтому
число 36 — это число успешно нормализованных записей, а не замаскированное
число попыток.

## 2. Кандидатная математическая методика

### 2.1. Категории и веса

Весовая политика соответствует целевому ТЗ для шести категорий:

| Категория `j` | Обозначение | Вес `w_j` |
|---|---:|---:|
| Documentation | `D` | 0.15 |
| Activity | `A` | 0.15 |
| Issues | `I` | 0.15 |
| CI/CD | `C` | 0.15 |
| Security | `S` | 0.20 |
| Code Health | `H` | 0.20 |
| **Итого** |  | **1.00** |

Эти числа — не утверждение научного стандарта. Это product prior, заданный ТЗ;
научные источники подтверждают необходимость явной weighting policy и
sensitivity analysis, но не выводят именно эти шесть чисел.

### 2.2. Evidence quality и coverage

Для каждой категории определяется качество наблюдения:

```text
q_j = clamp(coverage_j, 0, 1) × clamp(confidence_j, 0, 1)
```

Для `NOT_APPLICABLE`, `UNAVAILABLE` и `ERROR` принимается `q_j = 0`. Для
`MEASURED` и безопасного `NO_ACTIVITY` значение берётся из фактического
результата analyzer-а. `NO_ACTIVITY` не означает плохое здоровье: он означает,
что наблюдаемая активность отсутствует или не имеет достаточного sample для
вывода; numeric zero допускается только если analyzer действительно измерил
негативный сигнал.

Итоговая evidence coverage:

```text
K = Σ_j(w_j × q_j) / Σ_j(w_j)
```

`K` не умножает score. Он отвечает на другой вопрос: какая доля настроенного
веса подтверждена пригодными фактами.

### 2.3. Базовый score при частичных данных

Категория допускается в численный агрегат только если одновременно:

```text
category_status == MEASURED
score is not null
0 <= score <= 100
```

Тогда:

```text
H_raw = Σ_{j ∈ E}(w_j × C_j) / Σ_{j ∈ E} w_j
```

где `E` — множество измеренных категорий с numeric score.

Это означает controlled renormalization: недоступная категория не превращается
в ноль и не уничтожает измеренную часть, но её вес не исчезает из `K`. Поэтому
число можно показать как provisional, но нельзя выдавать за полноценный score
при недостаточном evidence.

### 2.4. Presentation state

Кандидатные release thresholds:

| Условие | State |
|---|---|
| `H_raw` отсутствует, или `K < 0.50`, или меньше 3 numeric eligible categories | `INSUFFICIENT_DATA` |
| `H_raw` существует и `K >= 0.50`, но full-score gate не пройден | `PROVISIONAL_SCORE` |
| `K >= 0.75`, минимум 4 numeric eligible categories, Security и Code Health имеют `q >= 0.75`, нет `UNAVAILABLE/ERROR` | `SCORE` |

Для `PROVISIONAL_SCORE` отображаются `H_raw`, `K`, список missing/partial
категорий и ограничения. Для `INSUFFICIENT_DATA` numeric промежуточные значения
могут сохраняться в diagnostics, но публичный итоговый score должен быть `null`.

Порог 0.50/0.75 — наша release policy, не научная константа и не продолжение
старого порога 70%. На доступной выборке пороги не удалось статистически
калибровать из-за отсутствия Security и CI. Перед production freeze их нужно
повторно проверить на полной шестикатегорийной когорте.

### 2.5. Security gate/cap

Если Security действительно измерен и evidence содержит подтверждённую
критическую уязвимость или secret exposure, применяется non-compensatory gate:

```text
H_final = min(H_raw, 40)
```

Если Security `UNAVAILABLE` или `ERROR`, cap не применяется автоматически:
отсутствие наблюдения не доказывает наличие критической проблемы. В этом случае
`K` уменьшается, а state не может быть полноценным `SCORE`.

Code Health отдельного hard cap сейчас не получает: его критические сигналы
должны оставаться в основном Code Health score и evidence. Наличие CI само по
себе не даёт бонуса; измеренное отсутствие CI — это отдельная policy-ситуация,
а unavailable CI не равен failure.

## 3. Почему выбран hybrid, а не одна средняя

Были проверены три модели.

| Модель | Формула/поведение | Результат оценки |
|---|---|---|
| A. Weighted arithmetic | `Σ(w_j C_j) / Σw_j` по eligible категориям | Самая прозрачная, линейная и удобная для breakdown; допускает компенсацию |
| B. Weighted geometric | `exp(Σw_j ln(C_j+ε)/Σw_j)` | Сильнее наказывает низкие значения, чувствительна к `ε`, плохо объясняется при нулевом score и missing data |
| C. Hybrid | arithmetic + evidence gates + critical cap | Сохраняет объяснимость A и запрещает недопустимую компенсацию критической Security-проблемы |

На synthetic reference `C_j = 85` все модели дают 85. При одной измеренной
critical Security-проблеме (`Security=0`, остальные `85`):

| Модель | Результат |
|---|---:|
| Arithmetic | 68.00 |
| Geometric (`ε=10⁻⁶`) | 2.21 |
| Hybrid с cap 40 | 40.00 |

Arithmetic показывает, что 20% Security недостаточно, если critical finding
можно компенсировать остальными категориями. Geometric превращает выбор
`ε` в скрытый policy knob и практически обнуляет весь результат. Hybrid
формально оставляет агрегат объяснимым, но устанавливает для доказанного
критического состояния верхнюю границу 40.

Ответ на вопрос о compensability: Documentation=100 не должна компенсировать
подтверждённую critical Security-проблему. Она может улучшить `H_raw` после
устранения проблемы, но до устранения действует cap.

## 4. Что показала реальная выборка

### 4.1. Статусы и распределения категорий

Ниже значения рассчитаны только по 36 успешным записям. `n(score)` — число
репозиториев, где категория дала numeric score; `missing` — доля без numeric
score.

| Категория | Статусы | `n(score)` | Среднее | Min | P10 | P25 | P50/медиана | P75 | P90 | Max | Median coverage/confidence | Missing |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Documentation | 32 `COMPLETED`, 4 `UNAVAILABLE` | 32 | 99.958 | 99.424 | 99.985 | 100.000 | 100.000 | 100.000 | 100.000 | 100.000 | 1.000/1.000 | 11.1% |
| Activity | 35 `MEASURED`, 1 `UNAVAILABLE` | 35 | 33.668 | 7.501 | 13.191 | 16.062 | 30.013 | 45.006 | 59.122 | 91.908 | 1.000/1.000 | 2.8% |
| Issues | 36 `PARTIAL` | 0 | — | — | — | — | — | — | — | — | 0.000/0.000 | 100% |
| CI/CD | 1 `MEASURED`, 1 `ERROR`, 34 `UNAVAILABLE` | 1 | 81.985 | 81.985 | 81.985 | 81.985 | 81.985 | 81.985 | 81.985 | 81.985 | 0.000/0.000 | 97.2% |
| Security | 36 `UNAVAILABLE` | 0 | — | — | — | — | — | — | — | — | 0.000/0.000 | 100% |
| Code Health | 36 `PARTIAL` | 36 | 82.492 | 74.792 | 77.219 | 78.346 | 81.779 | 82.138 | 94.624 | 100.000 | 0.667/0.825 | 0% numeric, но все partial |

Среднее Activity не следует интерпретировать как «репозитории в среднем плохие»:
это распределение текущей PyDriller-derived activity policy, а не экспертная
разметка здоровья. Аналогично Code Health в этой калибровке не имел SonarQube
coverage и в основном отражал git-sizer/Git-history signals.

### 4.2. Итоговые H_raw и K

| Показатель | Значение |
|---|---:|
| `H_raw` mean | 72.479 |
| `H_raw` median | 71.260 |
| `H_raw` min–max | 50.251–100.000 |
| `K` mean | 0.377 |
| `K` median | 0.410 |
| `K` min–max | 0.067–0.560 |
| `INSUFFICIENT_DATA` | 35 из 36 |
| `PROVISIONAL_SCORE` | 1 из 36 |
| полноценный `SCORE` | 0 из 36 |

Fixture `artem03102006/codex-external-audit-public-20260916` дал:

- Documentation `99.600`;
- Activity `75.140`;
- CI/CD `81.985` на 16 реальных runs;
- Issues — 1 open/unanswered issue, sample недостаточен для scored category;
- Code Health `82.140`, partial без SonarQube;
- Security `UNAVAILABLE`;
- `H_raw = 84.518`, `K = 0.560`, state `PROVISIONAL_SCORE`.

Этот результат показывает правильное missing-data behavior: fixture не получает
ноль из-за недоступного Security, но и не получает полноценный `SCORE`.

### 4.3. Обнаруженные аномалии и потолочные эффекты

Проверка не пыталась объяснить каждый score как ground truth. Она искала места,
где числовой результат может выглядеть убедительнее фактического evidence:

- Documentation имеет выраженный ceiling effect: у 32 scored repos медиана и
  P75 равны 100, а весь observed range — только `99.424–100.000`. Это не
  доказывает ошибку Vale, но означает, что текущий Vale contribution почти не
  разделяет хорошие documentation samples в этой выборке.
- На fixture CI score равен `81.985` при failure rate `31.25%` (`5/16` runs).
  Это подтверждает ранее подозреваемый anchor: reliability component не должен
  интерпретироваться как «CI хороший» без breakdown по failure rate, streak,
  sample и trend. Пороговые значения CI нужно повторно проверить на большем
  measured cohort.
- Молодые репозитории могут получить высокий Activity score из-за recency
  signal: например `dqdkfa/libmdbx` имел `91.908` при latest activity age около
  2.15 дней, а fixture — `75.140` при age около 4.62 дней. Это не обязательно
  баг, но это размерно-временная чувствительность, которую нельзя смешивать с
  доказательством зрелого contributor health.
- Подозрение «Code Health около 79 при complexity=0» не подтвердилось как
  измеренная complexity value: у таких записей `complexity_component = null`,
  потому что SonarQube unavailable. Следовательно, этот сигнал должен быть
  marked partial/unavailable, а не трактоваться как низкая complexity.
- Большая часть Issues samples была ограничена pagination/comment/state
  coverage. Пустой API result не трактовался как «идеальный backlog».

Эти anomalies оставлены как calibration follow-ups; ни одна не исправлялась
ручной подстановкой в dataset.

### 4.4. Почему полная калибровка пока не завершена

Зафиксированы реальные boundary limitations:

1. Для 34 публичных репозиториев SourceCraft CI endpoint вернул `403
   listCIFlux`; ещё один запрос получил `429`. Эти записи сохранены как
   `UNAVAILABLE/ERROR`, а не как zero runs.
2. В текущем OpenAPI/PAT boundary не обнаружен AppSec findings endpoint.
   Security не заменялся Scorecard, GitHub API или другим сканером.
3. Все 36 Issues records были `PARTIAL`: в публичном прогоне не сформировался
   полноценный scored cohort из-за неполной comment/date/state coverage.
4. Code Health был `PARTIAL` у всех 36: git-sizer и Git-history отработали,
   SonarQube Web API в этот прогон не подключался.

Следовательно, текущий прогон является валидным тестом воспроизводимости,
missing-data semantics и частичной sensitivity, но не доказательством того,
что веса и thresholds окончательно оптимальны для всех шести категорий.

## 5. Double counting и корреляции

Корреляции рассчитаны Spearman rank correlation по доступным парам. Из-за
missing categories это exploratory analysis, а не причинный вывод.

| Пара | n | Spearman | Интерпретация |
|---|---:|---:|---|
| Activity ~ Code Health | 35 | 0.037 | практически нет статистического совпадения в этой выборке |
| Documentation ~ Activity | 32 | 0.196 | слабая связь; prose и Git activity не одно и то же |
| Documentation ~ Code Health | 32 | 0.118 | слабая связь; Vale не дублирует maintainability |
| Activity score ~ Issues open | 35 | 0.256 | общая maintenance context, но разные источники/denominators |
| Issues open ~ CodeHealth git structure | 36 | -0.039 | совпадение не обнаружено |
| Activity score ~ Documentation findings | 32 | -0.244 | слабый exploratory сигнал, не основание для удаления веса |
| CI/CD с любой другой категорией | 1 | — | вывод невозможен |
| Security с любой категорией | 0 | — | вывод невозможен |

Semantic review остаётся обязательным поверх корреляции:

- Activity/CI могут совместно расти в зрелых проектах, но Activity измеряет
  Git-history, а CI — execution outcomes;
- Activity/Issues связаны общей maintenance population, но используют разные
  event streams и знаменатели;
- CI/CD/Code Health могут коррелировать через engineering maturity, но failure
  rate не является complexity/maintainability;
- Documentation/Code Health оба смотрят на files, но Vale работает с prose
  population, а Code Health — с code/structure population.

Поэтому ни одна пара не была автоматически дедуплицирована. Каждая category
получает один aggregate score, а внутренние metrics не попадают в top-level
formula отдельно.

## 6. Sensitivity analysis

Сравнивались candidate weights с равными весами и альтернативными policy
variants. В таблице `delta` — абсолютное изменение `H_raw` относительно
candidate, `rho` — Spearman по rank.

| Variant | Mean Δ | Max Δ | Spearman `rho` | n |
|---|---:|---:|---:|---:|
| Candidate 15/15/15/15/20/20 | 0.000 | 0.000 | 1.0000 | 36 |
| Equal 16.67 each | 1.349 | 5.344 | 0.9961 | 36 |
| Security/Code Health = 15/15 | 2.037 | 8.221 | 0.9884 | 36 |
| Security/Code Health = 25/25 | 1.969 | 7.125 | 0.9915 | 36 |
| Maintenance-focused 10/20/20/10/20/20 | 6.115 | 9.236 | 0.9954 | 36 |

На partial cohort ранжирование устойчиво: даже изменение веса давало `rho >=
0.9884`. Абсолютный score чувствительнее ranking, поэтому число нельзя
публиковать без policy version/digest.

Coverage thresholds были проверены на `.40`, `.50`, `.60`, `.70`, `.75`, `.80`.
На этой выборке при любом пороге 35 записей были `INSUFFICIENT_DATA`, одна —
`PROVISIONAL_SCORE`, и ноль — `SCORE`. Это не подтверждает конкретное значение
порога; причина — одинаковое отсутствие Security/CI, а не устойчивость порога.

### 6.1. Security cap sensitivity

На synthetic anchors tested caps `30/40/50/60`. Для reference с `H_raw=80`
и confirmed critical Security итог будет соответственно `30/40/50/60`.

Выбран cap `40` как candidate policy: он заметно ограничивает compensation,
но не утверждается как эмпирически окончательный. Его нужно повторно
проверить на реальных AppSec findings с различными remaining category scores.

### 6.2. Confidence intervals

Confidence interval для ranking всей методики сейчас не публикуется: 36 записей
не являются независимой случайной выборкой, Security и CI практически
отсутствуют, а часть репозиториев отобрана из одного SourceCraft catalog.
Bootstrap по этой выборке создавал бы точность вокруг boundary bias, а не вокруг
генеральной совокупности. После получения полной cohort можно добавить
bootstrap CI для median score, rank correlation и threshold pass-rate; это не
должно менять `score` конкретного репозитория.

## 7. Counterfactual и anti-gaming checks

Synthetic scenarios запускались тем же deterministic lab, что и базовая формула.
Delta считается относительно reference `H_raw=85`.

| Сценарий | Ожидаемое направление | Наблюдаемый `H_raw`/state |
|---|---|---|
| Critical vulnerability/secret | резкое снижение, без компенсации Documentation | `40.0`, `SCORE` через cap |
| Security API unavailable | score не становится нулём, state ухудшается | `85.0`, `K=0.80`, `PROVISIONAL_SCORE` |
| 100 empty commits | Activity снижается | `79.0`, delta `-6.0` |
| 1 issue вместо нормального sample | не давать сильный Issues вывод | `77.5`, `K=0.856`, `PROVISIONAL_SCORE` |
| CI failure rate около 30% | умеренное снижение reliability | `82.0`, delta `-3.0` |
| CI configured=false | измеренное отсутствие, не бонус за сам факт CI | `72.25` при local CI score `0` |
| CI API unavailable | не считать это failure rate 100% | numeric CI omitted, `K` ниже, provisional/insufficient |
| Documentation резко улучшается | score растёт только на её 15% | `86.95`, delta `+1.95` |
| Complexity резко ухудшается | Code Health существенно снижает итог | `75.0`, delta `-10.0` |
| Code Health engine unavailable | не превращать missing в zero | `85.0`, `K=0.80`, `PROVISIONAL_SCORE` |
| Маленький новый repo | не наказывать за отсутствие истории как за defect | `K=0.544`, `PROVISIONAL_SCORE` |
| Зрелый большой repo | полный score при полном evidence | `89.6`, `SCORE` |

Дополнительные anti-gaming anchors дали ожидаемое направление: закрытие Issues
без ответа `-6.0`, удаление тестов `-6.0`, отключение CI `-7.5`, множество
tiny/empty commits `-4.5/-6.0`. Filler в README дал только bounded delta
`-3.75`, а не линейный штраф за размер текста. Generated/vendor paths должны
быть исключены на уровне Code Health до top-level aggregation.

## 8. Источники: что именно ими подтверждено

| Источник | Подтверждено источником | Как применено | Происхождение числа |
|---|---|---|---|
| [OECD/JRC Handbook](https://doi.org/10.1787/9789264043466-en) | Composite indicators требуют явной normalization, weighting, aggregation, missing-data policy, correlation и sensitivity analysis | Основа структуры методики, `K`, sensitivity и запрета скрывать missing data | Не задаёт наши weights/thresholds/cap |
| [Linåker et al., OpenSym 2022](https://arxiv.org/abs/2208.01105) | OSS health — многомерная конструкция, а не одна activity metric | Обоснование шести разных измерительных популяций и evidence breakdown | Не задаёт top-level formula |
| [OpenSSF Scorecard](https://github.com/ossf/scorecard) | Industry practice: checks агрегируются risk-weighted, критичные проверки имеют больший impact | Поддерживает explicit weights и risk-sensitive handling | Не копируем Scorecard checks или веса |
| [OpenSSF Criticality Score](https://github.com/ossf/criticality_score) | Criticality — важность/контекст проекта, а не health | Не смешиваем criticality с quality score | Никаких чисел в health formula |
| [CHAOSS project health](https://www.chaoss.community/kb/metrics-model-starter-project-health/) и [responsiveness](https://www.chaoss.community/kb/metric-issue-response-time/) | Нужны измеримые project-health и response-time dimensions с явными denominators | Поддерживает Issues responsiveness/backlog/resolution, но не задаёт aggregation | Пороги Issues остаются category policy |
| [DORA metrics](https://dora.dev/guides/dora-metrics/) | Delivery metrics должны иметь настоящие deployment/change/recovery semantics | CI runs не превращаются в псевдо-DORA без deployment data | Нет DORA thresholds в top-level |
| [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html) | Quality model — multidimensional quality characteristics | Поддерживает separation maintainability, reliability и usability-like concerns | Не задаёт Repo Health score |
| [SonarQube metric definitions](https://docs.sonarsource.com/sonarqube-community-build/user-guide/code-metrics/metrics-definition) | Даёт definitions complexity, duplication, debt, LOC и quality metrics | Только semantic source для Code Health | Не задаёт category/top-level weights |
| SourceCraft Repo Health 2026 product TЗ и существующие contracts | Шесть категорий, 0–100, evidence, coverage/confidence, missing != bad; ориентир Security/Code Health 20% | Product constraints и release states | 15/15/15/15/20/20 — наша policy interpretation ТЗ |

Разделение принципиально: источники подтверждают construct validity, definitions
и нужду в governance; `0.50`, `0.75`, cap `40`, веса и sample release gate — наша
калибровочная политика, которую нужно версионировать и периодически пересматривать.

## 9. Финальная кандидатная спецификация

До production freeze рекомендуется зафиксировать policy как
`repo-health-score-candidate-v1`:

```text
weights = {
  Documentation: 0.15,
  Activity:      0.15,
  Issues:        0.15,
  CI/CD:         0.15,
  Security:      0.20,
  Code Health:   0.20,
}

q(category) = clamp(coverage, 0, 1) * clamp(confidence, 0, 1)
             (0 for NOT_APPLICABLE, UNAVAILABLE, ERROR)

K = sum(weight[j] * q[j]) / sum(all weights)

E = {j | status[j] == MEASURED and score[j] is numeric}
H_raw = sum(weight[j] * score[j] for j in E) / sum(weight[j] for j in E)

if confirmed_critical_security:
    H_final = min(H_raw, 40)
else:
    H_final = H_raw

if H_raw is null or K < 0.50 or len(E) < 3:
    state = INSUFFICIENT_DATA
elif K >= 0.75 and len(E) >= 4 and
     q(Security) >= 0.75 and q(CodeHealth) >= 0.75 and
     no category is UNAVAILABLE or ERROR:
    state = SCORE
else:
    state = PROVISIONAL_SCORE
```

Не следует вычислять `H_final × confidence`: это скрывает uncertainty внутри
одного числа и делает сравнение между репозиториями непрозрачным. Неопределённость
показывается отдельными полями `state`, `K`, category coverage/confidence и
limitations.

### 9.1. Изменения относительно candidate methodology

| Параметр | Candidate до калибровки | Рекомендация после текущего прогона | Решение |
|---|---|---|---|
| Top-level weights | 15/15/15/15/20/20 | те же | Не менять: rank sensitivity хорошая, но full-data cohort отсутствует |
| `K` provisional threshold | 0.50 | 0.50 | Оставить условно; выборка не позволяет доказать оптимальность |
| `K` full threshold | 0.75 | 0.75 | Оставить условно; дополнить essential-category gate |
| Minimum eligible categories | не формализован | 3 для provisional, 4 для full | Уточнить как explainable completeness rule |
| Security/Code Health quality | дополнительное требование | `q >= 0.75` для обеих в full score | Формализовать, чтобы partial engines не скрывались в high score |
| `UNAVAILABLE/ERROR` | missing-data semantics | запрещают full `SCORE`, но не делают score равным нулю | Зафиксировать явно |
| Security cap | `min(H_raw, 40)` | тот же cap как candidate | Не повышать/не понижать без реального AppSec cohort; anchors подтверждают направление, не оптимум |
| Confidence | отдельное поле | не умножать на score | Не менять; это наиболее объяснимый missing-data behavior |

Иными словами, текущая калибровка не нашла достаточного empirical evidence для
изменения чисел candidate. Она добавила строгую operational semantics и показала,
что numerical freeze сейчас был бы преждевременным.

## 10. Release gate перед реализацией Score Engine

Текущая методика готова как reproducible candidate, но не как окончательно
подтверждённая production calibration. Перед реализацией production aggregation
нужно:

1. Получить AppSec access и повторить прогон минимум на 30 реальных репозиториях,
   из них не менее 24 с `Security q >= 0.75`.
2. Получить CI permission/fixture cohort минимум на 30 репозиториях, включая
   success, repeated failures, cancelled/skipped и duration distributions.
3. Обеспечить Issues comment/state coverage, чтобы минимум 24 репозитория имели
   scored Issues components, а не только `PARTIAL` facts.
4. Повторить SonarQube-backed Code Health для зрелых и маленьких repos и
   проверить, что structural signals не создают размерный bias.
5. Повторить correlations, weight sensitivity, cap anchors и counterfactuals.
6. Сохранить policy version/digest вместе с каждым итоговым score.

Если после этого rank stability останется высокой, missing-data semantics не
изменятся, а critical cap будет подтверждён реальными AppSec scenarios, policy
можно переводить из `candidate-v1` в production revision.

## 11. Неизменённые границы

В этом исследовании не менялись:

- Vale, PyDriller, Issues, CI/CD, Security и Code Health analyzers;
- Global Score Engine;
- frontend и API presentation;
- SourceCraft API contracts;
- legacy documentation о старой восьмимерной схеме.

Файлы в `spikes/scoring/calibration/` — экспериментальные артефакты, а runner
не является production runtime.
