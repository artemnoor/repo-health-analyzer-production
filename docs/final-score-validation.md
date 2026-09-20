# Финальная empirical validation Repo Health Score

Статус: `VALIDATION COMPLETE / FORMULA NOT FROZEN`.

Этот документ фиксирует отдельную проверку только трёх категорий, для которых
до этого не хватало настоящего production-like SourceCraft наблюдения:

1. `Security` — SourceCraft AppSec;
2. `Issues` — SourceCraft issues/comments;
3. `CI/CD` — SourceCraft CI runs.

`Documentation`, `Activity`, `Code Health`, production Score Engine и формулы
остальных категорий в этой работе не перекалибровывались и не изменялись.

## 1. Что именно проверялось

Дата среза: `2026-09-20 23:59:59 UTC`.

Окно Issues и CI/CD: последние `90` дней. Это то же policy-окно, которое
использует существующий production boundary. Целью была не демонстрация того,
что API отвечает, а проверка более строгого условия: источник должен дать
достаточно полные факты, чтобы категория получила числовой score и чтобы этот
score можно было сопоставить с реальным сигналом.

Использовались:

- текущий SourceCraft REST API;
- текущие `issues_prs_adapter` и `CICDAnalyzer`;
- существующий fixture
  `artem03102006/codex-external-audit-public-20260916`;
- PAT только из `SOURCECRAFT_PAT`;
- уже накопленный live CI artifact для fixture, когда повторный запрос был
  rate-limited;
- существующий deterministic formula lab из `spikes/scoring/formula_lab.py`.

Ни один PAT, body issue/comment, исходный код, log или AppSec report body в
результаты не записывались. Новый spike-runner также явно отмечает
`raw_payloads_written: false`.

Воспроизводимый redacted artifact:

- [results.json](<C:/Users/Артём/Documents/ChatGPT/Yandex_full-module-extract-analyzer-integration-core-5865c9-5865c9a2-86b7-4c5a-9e6a-68607e393b32/spikes/scoring/final-validation/results.json>)
- [run_final_validation.py](<C:/Users/Артём/Documents/ChatGPT/Yandex_full-module-extract-analyzer-integration-core-5865c9-5865c9a2-86b7-4c5a-9e6a-68607e393b32/spikes/scoring/final-validation/run_final_validation.py>)
- [run_public_boundary_probe.js](<C:/Users/Артём/Documents/ChatGPT/Yandex_full-module-extract-analyzer-integration-core-5865c9-5865c9a2-86b7-4c5a-9e6a-68607e393b32/spikes/scoring/final-validation/run_public_boundary_probe.js>)

Запуск:

```powershell
.venv/Scripts/python.exe spikes/scoring/final-validation/run_final_validation.py
```

Токен нужен только в environment и никогда не выводится runner-ом.

## 2. Критерий готовности

Для категории считалось, что её формула подтверждена, только если одновременно
выполнены условия:

- есть несколько реальных репозиториев, а не один fixture;
- есть измеряемый numeric category score;
- есть достаточный sample size для заявленных percentile/trend выводов;
- coverage/confidence не ниже policy-gate;
- missing API/data остаётся отдельным status и не превращается в zero;
- реальные негативные сигналы дают ожидаемое направление score;
- нет возможности выдать высокий score на одном случайном наблюдении;
- результат повторяем на том же snapshot.

Synthetic и controlled сценарии могут подтвердить арифметику, monotonicity,
caps и missing-data semantics, но не заменяют real category cohort.

## 3. Security: результат проверки

### 3.1. Реальный SourceCraft путь

В target fixture действительно существуют workflows:

- `appsec-sast`;
- `appsec-secrets`;
- `appsec-sca`.

В CI history присутствуют успешные AppSec workflow runs, поэтому сам факт
наличия CI/AppSec configuration подтверждён. Однако для Repo Health этого
недостаточно: нужен доступ к содержимому SAST/SCA/Secrets result artifact.

Были проверены следующие REST-классы endpoint-ов:

| Endpoint class | Реальный результат |
|---|---:|
| `/repos/.../appsec` | `404` |
| `/repos/.../security` | `404` |
| `/repos/.../appsec/runs` | `404` |
| `/repos/.../security/scans` | `404` |
| `/repos/.../vulnerabilities` | `404` |

Также был выполнен штатный fixture readback через SourceCraft
`FileDownloadService`:

- `secrets/gitleaks`, run `16` — `UNIMPLEMENTED`;
- `sast/semgrep`, run `8` — `UNIMPLEMENTED`.
- `secrets/gitleaks`, run `8` — `UNIMPLEMENTED`;
- `sca/syft`, run `8` — `UNIMPLEMENTED`.

Тело report не сохранялось. SCA отдельным numeric результатом не объявлялся,
поскольку тот же boundary не вернул доступный report payload.

После этого был проверен ещё один официальный boundary — не только guessed
REST paths, но и опубликованный [SourceCraft OpenAPI JSON specification](https://api.sourcecraft.tech/sourcecraft.swagger.json):

- specification содержит `167` paths;
- paths для AppSec findings, vulnerability list, SARIF или security scan в
  опубликованной схеме не обнаружены (`0` paths);
- CI artifact path в схеме присутствует, поэтому он был проверен отдельно;
- для `run=8` были запрошены artifact lists для `semgrep`, `sast-upload`,
  `gitleaks`, `secrets-upload`, `syft`, `sca-upload`;
- для `run=16` дополнительно проверен `gitleaks`;
- все семь ответов — HTTP `200`, но каждый содержит `artifacts: []`.

Это сильнее, чем просто «endpoint не угадали»: опубликованный REST contract не
обещает AppSec findings resource, а доступный CI artifact contract не содержит
результатов сканов на проверенных runs. При этом официальная документация
SourceCraft подтверждает, что SAST, secret scan и SCA существуют в UI и умеют
показывать findings/SARIF/SBOM; это подтверждает наличие продукта, но не
доступность данных через текущий PAT/API boundary: [SAST](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/operations/sast),
[secret scanning](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/operations/secret-scan),
[SCA](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/operations/supply-chain).

### 3.1a. Проверка внутреннего UI boundary

Поскольку официальный UI показывает security pages, spike дополнительно
проверил read-only операции, которые использует отданный UI-клиент:
`getAppsecRepoStatus`, `getAppsecRepoScanStatus`, `getRepoSecurityStats`,
`listAppsecScans`, `listDefectsGroups`, `listAppsecArtifacts`. Фактический
transport — `/gateway/root/api/<operation>`, а не public OpenAPI.

Для всех шести операций web CSRF header и session-cookie были получены без
записи их значений, затем тот же `SOURCECRAFT_PAT` передан как
`Authorization: Bearer`. Ответ во всех случаях — HTTP `401`,
`GATEWAY_REQUEST_ERROR`, grpc status `401`; body операции не сохранялся.

Чтобы отделить PAT scope от public UI authorization, те же шесть операций были
повторены с CSRF/session-cookie, но без `Authorization` header. Все шесть снова
вернули HTTP `401` и только generic error schema с ключами
`code/details/message/status`. Это означает, что даже public repository UI
gateway не предоставляет anonymous AppSec readback в текущем boundary.

Следовательно, AppSec UI boundary существует, но требует web/IAM session и не
является доступным PAT API boundary. Наличие findings в UI нельзя использовать
как measured Security facts в текущем collector.

Чтобы не ограничиваться только guessed AppSec operations, browser probe также
прошёл по public repository pages и зафиксировал permission model, которую
отдаёт UI. Для `11` anonymous-visible repositories permission endpoint вернул
HTTP `200`, но `viewAppsec=false` и `useAppsec=false` во всех `11` случаях.
Private audit fixture anonymous session не открывает. Это не считается PAT
permission result: probe явно помечен как anonymous UI boundary. В совокупности
с шестью `401` на AppSec gateway operations он показывает, что public browser
session не является запасным источником findings для validation.

Дополнительно через официальный CI logs path были проверены четыре readback
task-а (`SAST`, `Secrets`, `SCA`, включая run `16`). Все HTTP `200`, но их
содержимое классифицировано как `grpc_unimplemented`; сами logs не сохранялись.

Чтобы исключить ошибку именно REST-wrapper boundary, был выполнен прямой
read-only вызов того же `FileDownloadService` по адресу
`appsec.sourcecraft.tech:443`, ровно по протоколу, который использует fixture
`appsec_readback.py`. Для run `8` были подтверждены repository UUID и commit
SHA ветки `appsec-pr-20260916`; для run `16` — commit SHA ветки
`codex/appsec-sca-secrets`. Проверены пять комбинаций:

- SAST / `semgrep` / run `8`;
- Secrets / `gitleaks` / run `8`;
- SCA / `syft` / run `8`;
- Secrets / `gitleaks` / run `16`;
- SCA / `syft` / run `16`.

Во всех пяти случаях transport вернул `UNIMPLEMENTED`. Это не результат
неизвестного commit или неверного scan id: commit был найден через официальный
`branches` API, а request собирался по fixture-протоколу. В redacted artifact
сохранены только branch/run/engine, transport status и gRPC code; report bytes,
finding text и package names не сохранялись.

Дополнительный owner-scoped discovery через `/user` и
`/orgs/{username}/repos` показал ровно два PAT-owned repositories: public и
private audit fixtures. Endpoint projects для того же owner вернул `403`, поэтому
скрытой третьей cohort через доступные owner-scoped REST paths обнаружить не
удалось.

### 3.1b. Проверка PR-comment boundary

Официальный [SourceCraft List Pull Request Comments API](https://sourcecraft.dev/portal/docs/en/api-ref/Repository-or-PullRequest-or-Comments/ListPullRequestComments)
также был проверен через PR comment paths. API contract явно допускает
`type=appsec` и resolution states `no_resolution_needed`, `awaiting_resolution`,
`resolved`:

- `/repos/.../pulls/1/comments` — HTTP `200`, `0` комментариев;
- `/repos/.../pulls/2/comments` — HTTP `200`, `1` комментарий.

Для второго ответа actor slug не содержал надёжного bot/security marker и сам
по себе был бы классифицирован как `unknown`. Однако у comment есть
официальное поле `type = appsec`, которое является более сильным признаком
происхождения, чем имя actor. Поэтому это зафиксировано как один реальный
AppSec-origin signal: comment опубликован, не удалён и имеет
`resolution_state=no_resolution_needed` — это не подтверждённый open
remediation item. Его body не сохранялся; из body извлекались только
агрегированные классы:

| Aggregate | Result |
|---|---:|
| PR comments with `type=appsec` | `1` |
| AppSec comments awaiting resolution | `0` |
| Resolved AppSec comments | `0` |
| AppSec comments with `no_resolution_needed` | `1` |
| Semgrep engine markers | `1` |
| AppSec comments with anchor metadata | `1` |
| Security Bot comments by actor marker | `0` |
| Human comments | `0` |
| Unknown actor comments | `1` |
| Severity words (`critical/high/medium/low`) | `0` |
| Resolved/fixed markers | `0` |

Таким образом, PR-comment boundary дал реальное partial SAST-origin evidence:
официальный comment type — `appsec`, body-class — `semgrep`, resolution state —
`no_resolution_needed`, anchor metadata присутствует. Но это всё ещё не
полный normalized finding:
severity и стабильный rule id отсутствуют, а structured report payload
недоступен. Поэтому validation boundary поднимается до `PARTIAL`, но
production Security category не объявляется fully measured.

### 3.2. Что реально измерено

| Показатель | Результат |
|---|---:|
| Репозитории с доступным AppSec findings payload | `0` |
| Реальные AppSec-origin PR comments | `1` в `1` repository |
| Реальные SAST-origin (`semgrep`) comments | `1` |
| Реальные structured SAST findings | не измерены |
| Реальные structured SCA findings | не измерены |
| Реальные structured secrets findings | не измерены |
| Severity/fixed-unfixed distribution | не измерена |
| Synthetic rows использованы как real | нет |
| Security validation boundary | `PARTIAL` |
| Production Security category | `UNAVAILABLE` |

Это важное различие: наличие workflow и его `SUCCESS` не означает, что
structured security findings доступны analyzer-у. Один `type=appsec` comment
доказывает наличие real AppSec signal, но не позволяет безопасно вычислить
severity-aware score. Нельзя считать это «0 vulnerabilities».

### 3.3. Вывод по Security

**Security formula ready: NO.**

Controlled synthetic anchors по-прежнему подтверждают только направление
политики: critical/secret signal должен запускать cap, а unavailable API не
должен запускать cap и не должен давать score `0`. Они не подтверждают
production severity mapping, fixed/unfixed semantics и distribution real
findings.

## 4. Issues: результат проверки

### 4.1. Cohort и качество фактов

Был проверен расширенный cohort из десяти реальных public repositories с
разной историей issue population. Collector получил реальные issue rows,
timestamps, states и compact actor metadata. Comment body нигде не
использовался.

| Repository | Issue rows | Sample в 90d | Open | Comments | Source status | Coverage | Confidence | Category score |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| `a-obraz60022006/mirea-trade` | 19 | 19 | 19 | 0 | `MEASURED` / `PARTIAL` analyzer | 0.70 | 0.52 | — |
| `k-5-45mm/dozzle-plus` | 73 | 73 | 73 | 0 | `PARTIAL` | 0.70 | 0.52 | — |
| `arceniytadevosyan/lmsweb` | 11 | 7 | 11 | 4 | `PARTIAL` | 0.70 | 0.70 | — |
| `astra-shellless-images/nginx` | 7 | 7 | 7 | 0 | `PARTIAL` | 0.70 | 0.52 | — |
| `astra-shellless-images/opensearch` | 36 | 36 | 36 | source error | `ERROR` / no score | 1.00 | 0.75 | — |
| `astra-shellless-images/tomcat` | 11 | 11 | 11 | 0 | `PARTIAL` | 0.70 | 0.52 | — |
| `fompronin/heh` | 10 | 8 | 10 | 11 | `MEASURED` / `PARTIAL` analyzer | 0.70 | 0.70 | — |
| `imbok/cosmos-ontology` | 35 | 35 | 35 | 11 | `PARTIAL` | 0.70 | 0.70 | — |
| `imbok/uims-portal` | 17 | 17 | 17 | 3 | `PARTIAL` | 0.70 | 0.70 | — |
| `sourcecraft/sourcecraft` | 500 safety bound | 0 | 500 | 201 | `PARTIAL` | 0.35 | 0.35 | — |

`Sample в 90d` — это population, из которой текущий analyzer может считать
responsiveness/resolution, а не просто количество исторических rows.

Исследовательский catalog probe проверил union из `1,978` public repository
entries; у `962` issue requests был HTTP `200`, а у `13` repositories в
первой странице реально обнаружился sample `>=5` в 90-дневном окне. Для
финального redacted artifact взяты десять из них. Доступность rows сама по
себе не решает проблему: production analyzer всё равно применяет собственные
coverage/comment/state gates.

Отдельный exploratory pass по `1,976` каталоговым repositories нашёл `15`
кандидатов с sample `>=5`. В первых пяти issues только у четырёх repositories
были human comments: `sourcecraft/sourcecraft`, `fompronin/heh`,
`compilators/dtl-26` и `imbok/uims-portal`. Это объясняет, почему в полной
финальной cohort response-latency observations остаются редкими: подавляющая
часть real issue population — unanswered, а не искусственно удалённая из
выборки. Сохранялись только counts и actor classes.

### 4.1a. Повторная проверка через официальный server-side filter

Чтобы отделить ограничение API от ограничения текущего collector boundary,
выполнен отдельный spike-only probe по документированному [List Repository
Issues API](https://sourcecraft.dev/portal/docs/en/api-ref/Issues/ListRepositoryIssues).
Использовался union двух запросов:

```text
created_at > "2026-06-22T23:59:59Z"
status = open
```

Оба запроса проходили через `page_token`, а результаты deduplicate не
сохранялись в raw-виде. Дополнительно фиксировалось наличие поля
`completed_at`, но сами issue payloads в artifact не записывались.

| Repository | Created in 90d | Completed-at rows | Open backlog | Pagination | Sample ≥5 in window |
|---|---:|---:|---:|---|---|
| `a-obraz60022006/mirea-trade` | 19 | 8 | 11 | complete | yes |
| `k-5-45mm/dozzle-plus` | 73 | 35 | 38 | complete | yes |
| `arceniytadevosyan/lmsweb` | 7 | 6 | 0 | complete | yes |
| `astra-shellless-images/nginx` | 7 | 0 | 7 | complete | yes |
| `astra-shellless-images/opensearch` | 36 | 21 | 15 | complete | yes |
| `astra-shellless-images/tomcat` | 11 | 0 | 11 | complete | yes |
| `fompronin/heh` | 8 | 0 | 10 | complete | yes |
| `imbok/cosmos-ontology` | 35 | 4 | 30 | complete | yes |
| `imbok/uims-portal` | 17 | 2 | 12 | complete | yes |
| `sourcecraft/sourcecraft` | 280 | 155 | 317 | complete | yes |

Таким образом, источник реально способен дать существенно более богатую
выборку, чем показал старый local-filter probe: все десять repositories имеют
как минимум пять issue, созданных в 90-дневном окне, и все десять дали полный
server-side response. Это закрывает именно вопрос наличия real issue
population для cohort, но не превращается
автоматически в production validation по двум причинам:

1. текущий production normalizer сохраняет `created_at`, `updated_at` и state,
   но не переносит SourceCraft `completed_at` в normalized `closed_at`;
2. SourceCraft endpoint отдаёт текущий state, comments и `completed_at`, но не
   state-transition history, поэтому reopened semantics остаётся
   `NOT_APPLICABLE`.

Первоначальный server-filter probe специально не подменял production facts
inferred-значениями и не менял collector/analyzer. Поэтому его table — это
подтверждение доступности источника и конкретный implementation gap. Для
отдельной проверки самой formula ниже выполнен изолированный scored probe.

### 4.1b. Spike-only scored probe на тех же real facts

Чтобы отделить качество candidate formula от старого collector boundary, был
запущен отдельный redacted scored probe. Он не меняет production collector:

1. получает те же десять реальных populations через server-side filters;
2. переносит SourceCraft `completed_at` в существующий normalized `closed_at`;
3. получает comments с полной pagination;
4. передаёт только нормализованный inventory в существующий IssuesAnalyzer;
5. сохраняет только CategoryResult summary и aggregate signals.

В ходе этой проверки обнаружился и был исправлен минимальный defect в
`IssuesAnalyzer`: synthetic `opened` event мог перекрывать более поздний
`closed_at`. Теперь state определяется единой временной timeline, где более
поздний explicit lifecycle event имеет приоритет. Score Engine при этом не
менялся. Добавлен regression test для stale/current-state mismatch.

После исправления все десять repositories получили числовой score:

| Repository | Score | Sample | Open | Closed | Closure ratio | Stale ratio | Human comments | Coverage / confidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `a-obraz60022006/mirea-trade` | 73.61 | 19 | 11 | 8 | n/a* | 0.00 | 0 | 1.00 / 0.75 |
| `k-5-45mm/dozzle-plus` | 56.11 | 73 | 38 | 35 | 0.914 | 0.079 | 1 | 1.00 / 1.00 |
| `arceniytadevosyan/lmsweb` | 18.25 | 7 | 1 | 6 | 0.833 | 1.000 | 0 | 1.00 / 0.75 |
| `astra-shellless-images/nginx` | 22.14 | 7 | 7 | 0 | 0.000 | 1.000 | 0 | 1.00 / 0.75 |
| `astra-shellless-images/opensearch` | 39.70 | 36 | 15 | 21 | 0.677 | 0.667 | 5 | 1.00 / 1.00 |
| `astra-shellless-images/tomcat` | 32.78 | 11 | 11 | 0 | 0.000 | 0.727 | 0 | 1.00 / 0.75 |
| `fompronin/heh` | 9.09 | 8 | 10 | 0 | 0.000 | 0.900 | 11 | 1.00 / 1.00 |
| `imbok/cosmos-ontology` | 11.59 | 35 | 31 | 4 | 0.114 | 0.968 | 18 | 1.00 / 1.00 |
| `imbok/uims-portal` | 29.94 | 17 | 15 | 2 | 0.286 | 0.333 | 4 | 1.00 / 1.00 |
| `sourcecraft/sourcecraft` | 52.88 | 280 | 409 | 155 | 0.653 | 0.819 | 932 | 1.00 / 0.99 |

\* Для `mirea-trade` закрытые issues ещё не достигли maturity window для
resolution component; это `NOT_APPLICABLE`/`UNAVAILABLE` для close-time
percentiles, а не нулевое время закрытия.

Descriptive checks по scored cohort:

- cohort size: `10`;
- numeric scores: `10/10`;
- score range: `9.09–73.61`, median `31.36`;
- все четыре components eligible: `6/10` repositories;
- Spearman(score, closure ratio): `+0.542`, `n=9`;
- Spearman(score, stale ratio): `−0.778`, `n=10`;
- Spearman(score, open backlog age median): `−0.564`, `n=10`;
- Spearman(score, unanswered ratio): `+0.112`, `n=10`;
- first-response latency observations: только `n=2`, поэтому latency
  distribution пока не считается empirically calibrated;
- reopened: `NOT_APPLICABLE` для всех десяти, поскольку state-transition
  history SourceCraft не отдаёт.

Полученные направления соответствуют policy: высокий stale ratio и старый
backlog понижают score, а closure ratio в целом повышает его. При этом probe
явно отметил outliers/anomalies:

- `mirea-trade` имеет score `73.61`, но human comments отсутствуют; это не
  подтверждение responsiveness, а score только по backlog/maintenance при
  confidence `0.75`;
- у `heh` и `sourcecraft/sourcecraft` текущий open backlog больше sample
  созданных issues в окне, потому что это разные populations;
- response latency недостаточно разнообразна для отдельной calibration;
- reopened нельзя проверить ни на одном repository.

Поэтому scored probe подтверждает направленность и воспроизводимость Issues
formula, но не закрывает все обязательные lifecycle signals.

### 4.2. Production boundary vs spike score

У существующего collector/analyzer одновременно наблюдались следующие
ограничения:

- `local_date_filter_applied = false`;
- comments часто неполны или их response pagination не завершена;
- `state_events_available = false`;
- для части large histories сработал safety bound `500` rows;
- при rate limit source error нельзя трактовать ответ как empty issue list.

Отдельный filtered probe дополнительно показал, что часть проблемы находится
не в SourceCraft API, а в текущем normalization boundary: `completed_at`
доступен в официальном issue response (и реально присутствует у 35 dozzle,
6 lmsweb и 155 sourcecraft rows), но production collector всё ещё не переносит
его в normalized row. Scored probe передал это поле явно только внутри spike;
production resolution component поэтому по обычному collector path всё ещё не
может честно использовать время закрытия. Это зафиксировано как blocker.

Это отражается в category diagnostics:

- counts — `MEASURED` или частично measured;
- responsiveness — `UNAVAILABLE`;
- resolution — `UNAVAILABLE`;
- backlog — `UNAVAILABLE` при недостаточной completeness;
- reopened — `NOT_APPLICABLE` без state events;
- обычный production collector path возвращает category score `None`, а не
  искусственный numeric zero;
- spike-only server-filtered path возвращает numeric score, но отдельно
  помечает его как validation evidence, не как production collector result.

В `lmsweb` наблюдались реальные негативные признаки: 7 issues в окне,
unanswered issues и высокий open backlog age. Но coverage `0.70` ниже
production policy `0.80`, поэтому analyzer не имеет права выдавать сильный
numeric verdict. Это корректное поведение для safety of measurement.

### 4.3. Проверка minimum sample

Ограничение `minimum_sample = 5` теперь подтверждено для всех десяти
server-filtered repositories, и spike-only scored probe получил `10/10`
numeric results. Но minimum sample — только необходимое условие. Для полного
freeze Issues также нужны достаточная response-latency cohort и state
semantics; reopened history не измеряется, а response latency наблюдалась
только в двух repositories.

### 4.4. Вывод по Issues

**Issues formula ready: NO.**

Причина теперь уже точнее: real scored cohort для counts/closure/stale/backlog
получена, и её направления ожидаемые, но response-latency calibration имеет
только `n=2`, reopened semantics полностью `NOT_APPLICABLE`, а обычный
production collector всё ещё теряет `completed_at` и применяет другой date /
comment boundary. Поэтому нельзя утверждать, что вся responsiveness/resolution
formula empirically validated для production cohort.

## 5. CI/CD: результат проверки

### 5.1. Target fixture: реальный mixed result

Для
`artem03102006/codex-external-audit-public-20260916` полный live SourceCraft
path был повторно выполнен штатным verifier-ом и затем подтверждён отдельным
CI-only collector probe. Это не synthetic row; текущий final runner получил
один paginated response с `16` records:

| Metric | Реальное значение |
|---|---:|
| Total runs | 16 |
| Success | 11 |
| Failure | 5 |
| Cancelled | 0 |
| Skipped | 0 |
| Success rate | 68.75% |
| Failure rate | 31.25% |
| Last run | `SUCCESS` |
| Failure streak | 0 |
| Duration P50 | 113.760477 s |
| Duration P95 | 185.129413 s |
| Stability trend | `unavailable` — нет previous comparable window |
| Analyzer score | 81.985294 |
| Analyzer status | `WARN` |
| Coverage/confidence | 1.0 / 1.0 |
| Findings | 1 high: failure rate 31.2% |

Intermediate full-cohort probe один раз получил transient `ERROR` после серии
SourceCraft requests; отдельный read-only запрос и следующий full/CI-only probe
снова вернули HTTP `200` и те же `16` runs. Этот transient результат не был
превращён в нулевой score: в artifact сохраняется collection status, а
measured CI facts берутся только из успешного run с `records_received=16`.

Component breakdown live result:

- reliability: `73.4375`;
- failure-streak health: `81.25`;
- duration: `100.0`.

Это подтверждает несколько важных свойств:

- failure rate около 30% действительно заметно влияет на category score;
- один последний успешный run не стирает пять failures;
- длительность не доминирует над reliability;
- отсутствие comparable previous window оставляет trend unavailable.

### 5.2. Второй PAT-доступный repository

Для приватного fixture
`artem03102006/codex-external-audit-private-20260916` API вернул:

- 4 runs;
- 2 success и 2 failure;
- success rate `50%`;
- failure rate `50%`;
- duration P50 `1.371206 s`;
- duration P95 `1.405956 s`;
- category status `INSUFFICIENT_HISTORY`;
- score отсутствует.

Это хороший negative control для sample gate: даже numeric status/failure
signals не превращаются в высокий confidence при истории всего из четырёх
runs.

### 5.3. Почему cohort всё ещё недостаточен

В массовом CI probe public catalog observed boundary был таким:

- проверено около 500 repository endpoints;
- `0` устойчиво measured responses;
- `493` ответа `403`;
- `7` ответов `429`.

Это дополнительно сверено owner-scoped discovery: текущий PAT видит ровно два
repository в `/orgs/artem03102006/repos`, и оба уже входят в live CI проверку
(public fixture и private insufficient-history control). Поэтому расширить CI
cohort только перебором доступных PAT-owned repositories в текущем состоянии
нельзя.

Права CI list/read доступны для target-owned fixture repositories, но не дают
несколько независимых healthy/mixed/failure-heavy public cohorts. Поэтому
реально проверены только два PAT-доступных repositories, из которых только
один имеет достаточную историю для numeric score.

Это не результат неправильного endpoint selection: официальный [SourceCraft
OpenAPI contract](https://api.sourcecraft.tech/sourcecraft.swagger.json)
описывает `GET /repos/{org_slug}/{repo_slug}/cicd/runs`, но для публичных
каталожных repositories текущий PAT получает `403` с permission boundary
`src.repositories.listCI`. Для owner-owned public/private fixtures этот же
path отвечает `200`. Следовательно, расширение CI cohort требует нового
read-scope/role или дополнительных owner-controlled repositories, а не
подмены данных другим CI provider.

Дополнительно проверена альтернативная форма того же официального API:
`GET /repos/id:{repo_id}/cicd/runs`. Для десяти public repositories, у которых
metadata и repository ID доступны, результат был одинаковым:

```text
slug path: 10 × HTTP 403
repository-ID path: 10 × HTTP 403
run records через ID path: 0
```

Таким образом, permission boundary не связан с формой slug URL; обход через
repository ID также не открывает CI history.

Проверен и третий независимый boundary — anonymous REST access к тому же
`/cicd/runs` для `12` repositories (два audit fixtures и десять public
кандидатов). Все `12` ответа были HTTP `401`, без records. Эти ответы не
помечаются как measured CI failures и не смешиваются с PAT-owned fixture
results; они только подтверждают, что public CI history нельзя получить без
доступного read-scope.

Не подтверждены на реальном cohort:

- healthy band `0–10%` failures на нескольких repositories;
- mixed band `10–30%` на нескольких repositories;
- failure-heavy band `30%+` на нескольких repositories;
- stable current-vs-previous trend;
- robust retry/flaky distribution.

DORA metrics здесь также не приписывались CI runs: deployment, production
environment, incident и restore events SourceCraft boundary не дал.

### 5.4. Вывод по CI/CD

**CI/CD formula ready: NO.**

Направление и один реальный mixed anchor подтверждены. Production freeze нельзя
делать, пока нет нескольких независимых measured repositories и второй
сопоставимой временной window для trend calibration.

## 6. Повторная проверка top-level policy

Проверена текущая кандидатная policy:

```text
Documentation  15%
Activity       15%
Issues         15%
CI/CD          15%
Security      20%
Code Health   20%
```

Coverage quality остаётся:

```text
q_j = clamp(coverage_j, 0, 1) * clamp(confidence_j, 0, 1)
K   = sum(w_j * q_j) / sum(w_j)
```

`K` не умножает numeric score. Он определяет, может ли score быть объявлен
полным или только provisional:

- `K >= 0.75` и essential category quality достаточна — кандидат на `SCORE`;
- `K >= 0.50` — `PROVISIONAL_SCORE`;
- ниже — `INSUFFICIENT_DATA`.

Security unavailable не запускает cap и не становится `Security = 0`. Confirmed
critical/secret finding запускает non-compensatory cap. Кандидатные caps:

- confirmed high: `60`;
- confirmed critical/secret: `40`.

Повторный deterministic formula lab дал следующие результаты:

| Проверка | Результат |
|---|---|
| Documentation monotonicity | pass |
| Complexity degradation monotonicity | pass |
| Security unavailable ≠ zero | pass |
| CI negative signal lowers score | pass |
| Critical Security cap | pass |
| One issue cannot produce full score | pass |
| Critical cap 40/50/60 sensitivity | output exactly equals selected cap |
| `K=.50/.75` on small-repo control | `PROVISIONAL_SCORE` |
| `K=.60/.80` on same control | `INSUFFICIENT_DATA` |

Это подтверждает воспроизводимость и direction of policy, но не доказывает,
что именно эти числа оптимальны для реального распределения Security/Issues/
CI repositories.

Ранее накопленная v2 sensitivity analysis на `32` observational и `15`
controlled records дала следующие ориентиры:

| Variant | Max absolute score delta | Mean absolute delta | Spearman vs candidate |
|---|---:|---:|---:|
| Equal weights | 5.17 | 1.92 | 0.9917 |
| Security/Code Health 25/25 | 7.76 | 2.86 | 0.9933 |
| Maintenance-focused | 6.22 | 3.21 | 0.9882 |

Но эти значения нельзя интерпретировать как окончательную external
validation: в observational cohort Security и CI в основном были unavailable,
а Issues часто были partial.

## 7. Итоговое решение

| Объект | Ready? | Основание |
|---|---|---|
| Security formula | **YES for controlled boundary / NO for production freeze** | Owner-controlled AppSec REST дал clean, SAST, SCA, synthetic-secret и fixed observations; production adapter и canonical severity enum ещё не зафиксированы |
| Issues formula | **NO** | 8 реальных issues измерены только как `PARTIAL`: completed_at сохранён, но SourceCraft не дал state-events, а одна actor identity не позволяет подтвердить положительную first-human-response latency |
| CI/CD formula | **YES for core reliability candidate / NO for full freeze** | Контролируемые 30% и 75% failure bands, healthy/insufficient controls и fixture 16 runs подтверждены; вторая time window, retry/flaky cohort и DORA events отсутствуют |
| Top-level Repo Health methodology | **NO** | Security boundary и CI candidate усилены, но Issues response/reopen semantics и cross-category real cohort всё ещё недостаточны |

Следовательно, финальная formula **не замораживается** и в production Score
Engine не переносится.

Текущее безопасное поведение сохраняется:

- отсутствие AppSec API — `UNAVAILABLE`, не security zero;
- incomplete issue comments/state — `PARTIAL`/`UNAVAILABLE`, не плохой score;
- мало CI runs — `INSUFFICIENT_HISTORY`, не высокий score и не failure rate 100%;
- SourceCraft HTTP error — error/unavailable boundary, не `NO_ISSUES`.

Последний пункт также стал отдельным validation finding: в одном transient issue
probe collector error наблюдался рядом с analyzer diagnostic `NO_ISSUES`. Этот
случай исключён из measured cohort и требует отдельной boundary regression
проверки до production freeze. В рамках этой validation изменён только
минимальный state-timeline defect в IssuesAnalyzer; Score Engine и остальные
категории не менялись.

## 8. Controlled validation на owner-controlled SourceCraft repositories

Публичный API permission boundary больше не используется как единственное
основание для остановки проверки. В текущем аккаунте созданы или повторно
использованы девять отдельных repositories с префиксом
`repo-health-calibration-`:

- `healthy` — clean AppSec control;
- `security` — Semgrep `eval`, уязвимый `django==2.2.0` и synthetic-only secret;
- `security-fixed` — та же security fixture после удаления проблемных файлов;
- `ci-healthy`, `ci-low` (`repo-health-calibration-ci-low`), `ci-mixed`,
  `ci-bad`, `ci-insufficient` — реальные SourceCraft workflows с разной
  историей runs;
- `issues` — реальные issues и comments через SourceCraft REST.

Репозитории не удалялись после проверки. Security controls были открыты как
public, чтобы SourceCraft AppSec uploader мог записать результаты; CI и Issues
controls остались private. PAT не записывался ни в repository, ни в logs,
`results.json` или документацию.

### 8.1. Security: восстановленная REST boundary

Рабочий путь оказался таким:

```text
Bearer PAT
  -> https://appsec.sourcecraft.tech/v1/scans?gitRepo=<internal-repository-id>
  -> /v1/defect-groups?scanUuid=<scan-uuid>&gitRepo=<internal-repository-id>
  -> /v1/findings?defectGroupUuid=<group-uuid>&gitRepo=<internal-repository-id>
```

Вызовы без `gitRepo` отвергались authorization boundary; с internal repository
ID возвращали `200`. В итоговый artifact сохраняются только redacted IDs,
engine/rule/severity/status/file и counts; source snippets, messages и raw
payloads не сохраняются.

| Controlled repo | Scans | Latest groups | Historical groups | Observed active status `0` | Observed status `9` | Findings payloads для active groups | Наблюдение |
|---|---:|---:|---:|---:|---:|---:|---|
| `healthy` | 4 | 0 | 0 | 0 | 0 | 0 | clean control |
| `security` | 12 | 1 | 154 | 3 | 151 | 3 | Semgrep, Opengrep, Trivy, grype, gitleaks |
| `security-fixed` | 10 | 0 | 51 | 0 | 51 | 0 | после fix активных групп нет |

Зафиксированы реальные controlled signals:

- Semgrep rule `repo-health-controlled-eval` на `bad.py`;
- Trivy CVE groups и grype GHSA groups для `django==2.2.0`;
- synthetic-only Gitleaks rule `repo-health-synthetic-secret`;
- после удаления fixture активные groups исчезли, а historical groups остались
  только как observed status `9`.

Числа `0` и `9` не объявляются официальной универсальной enum-расшифровкой:
это observed SourceCraft REST semantics текущей boundary. Статус `0`
подтверждён непустым `/findings` payload, а статус `9` — исторической группой
без active findings payload. Для production freeze нужен отдельный
versioned mapping из официального AppSec contract.

Итог: security candidate direction теперь реально проверена clean → finding →
fixed. Поэтому `Security formula ready` в controlled sense — `YES`; это ещё не
разрешение подключать формулу к global Score Engine: production AppSec adapter
и canonical severity mapping остаются обязательными.

### 8.2. Issues: real REST facts и честный partial result

На `repo-health-calibration-issues` через SourceCraft API создано `8` issues:
`5` open и `3` closed. Для закрытых объектов production normalization boundary
сохраняет SourceCraft `completed_at` как normalized `closed_at`; этот mapping
покрыт unit tests.

В API были добавлены пять comments. Все comments принадлежат той же
authenticated owner identity, которая создала issues. Production policy
правильно исключила их как self-authored: `first_human_response_count=0`,
`first_response_median_hours=null`, `unanswered_issues=8`. Это не ошибка
метрики и не означает, что comments отсутствуют: `comments_human=5`, но они не
являются ответом другого human actor.

Итог production analyzer:

```text
facts status     = PARTIAL
CategoryResult   = WARN
score            = null
coverage         = 0.0 at analyzer result level
confidence       = 0.0 at analyzer result level
open / closed    = 5 / 3
stale ratio      = 0.0
open age median  = 12.113791 hours
closure ratio    = unavailable
reopened         = NOT_APPLICABLE
```

Нулевой score здесь не выставлен. Score отсутствует, потому что positive
responsiveness и resolution components не имеют допустимых observed events;
это именно partial/unavailable behavior, а не verdict “issues category плохая”.

Повторная проверка Issues candidate v2 дала тот же результат: `candidate_v2_score`
остаётся `null`, потому что v2 не делает partial responsiveness/resolution
данные измеренными искусственно и не превращает sample `8` без допустимых
events в numeric verdict.

`Issues formula ready = NO` остаётся только по двум проверяемым причинам:

1. в текущем аккаунте есть одна actor identity, поэтому нельзя автономно
   создать доказуемый ответ второго human;
2. SourceCraft endpoint, использованный в этой boundary, не отдаёт state-event
   timeline, поэтому reopened semantics нельзя подтвердить.

### 8.3. CI/CD: production result против v2 candidate

Все runs пришли из настоящего SourceCraft `/cicd/runs`, без синтетической
подмены inventory. Для каждого control использовались обычные production
normalizer и `CICDAnalyzer`; non-production v2 формула применялась только как
второй столбец сравнения.

| Repository | Runs | Success / failure | Failure rate | P50 sec | P95 sec | Production score | v2 candidate | Production status | Facts status |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `ci-healthy` | 2 | 2 / 0 | 0% | 3.2769815 | 3.36106715 | — | — | INCONCLUSIVE | INSUFFICIENT_HISTORY |
| `ci-insufficient` | 1 | 1 / 0 | 0% | 3.208708 | 3.208708 | — | — | INCONCLUSIVE | INSUFFICIENT_HISTORY |
| `ci-low` | 10 | 8 / 2 | 20% | 3.40815 | 3.61932605 | 88.470588 | 85.0 | WARN | MEASURED |
| `ci-mixed` | 10 | 7 / 3 | 30% | 3.4812185 | 4.35337435 | 82.705882 | 77.5 | WARN | MEASURED |
| `ci-bad` | 8 | 2 / 6 | 75% | 3.3016985 | 3.5178705 | 40.249224 | 30.780029 | FAIL | MEASURED |
| public fixture | 16 | 11 / 5 | 31.25% | 113.760477 | 185.1294133 | 81.985294 | 76.5625 | WARN | MEASURED |

Контрольные выводы:

- 30% failure rate получил `WARN`, 75% — `FAIL`; направление совпадает у
  production и v2;
- одна и две успешные runs не получили score, несмотря на 100% success rate;
- cancelled/skipped не появились и не были ошибочно посчитаны failures;
- retry/flaky relation и current-vs-previous stability trend остаются
  `UNAVAILABLE`, потому что эти поля/event history отсутствуют в SourceCraft
  rows;
- все четыре DORA metrics — `NOT_APPLICABLE`: обычные CI runs не являются
  deployment/environment/incident evidence.

На fixture разница между текущим production analyzer и v2 candidate составляет
`5.422794` points (`81.985294 -> 76.5625`). Это не изменение production
behavior: v2 был запущен как calibration comparison, а Score Engine не
трогался.

`CI/CD formula ready = YES` только для core reliability candidate (failure
rate, streak, duration, sample gate). Теперь controlled cohort покрывает
`0%` insufficient/healthy control, `20%`, `30%` и `75%` failure bands. Полный
freeze всё ещё требует второй сопоставимой временной window, реальных
retry/flaky records и отдельного DORA-capable source.

### 8.4. Controlled validation artifacts и final readiness

Детализированный redacted snapshot находится в
[`spikes/scoring/final-validation/results.json`](../spikes/scoring/final-validation/results.json),
а воспроизводимый runner — в
[`spikes/scoring/final-validation/run_controlled_validation.py`](../spikes/scoring/final-validation/run_controlled_validation.py).

Контрольный итог:

| Required field | Result |
|---|---|
| Controlled repos created/reused | `9` |
| AppSec REST path works | `YES` |
| Real Security measured repos | `3` |
| Real Issues measured repos | `0` full / `1` partial real facts |
| Real CI measured repos | `3` full / `5` real controls |
| Security formula ready | `YES` for controlled candidate; production freeze pending adapter/enum |
| Issues formula ready | `NO`, only actor/state-event blockers remain |
| CI/CD formula ready | `YES` for core candidate; full freeze pending second window/retry evidence |
| Top-level methodology ready | `NO` |
| Production Score Engine changed | `NO` |

Следовательно, controlled validation сняла прежний внешний AppSec/CI blocker,
но не дала оснований притвориться, что top-level methodology уже frozen.
Следующий минимальный шаг перед Score Engine implementation — production AppSec
adapter, second-human/state-event Issues evidence, second CI window и после
этого повтор frozen sensitivity/correlation analysis.

## 9. Remaining blockers перед final YES

1. Добавить production `SourceCraft AppSecAdapter` поверх уже подтверждённой
   REST boundary и versioned mapping для severity/status enum.
2. Получить second-human response evidence и SourceCraft state-event timeline;
   при этом сохранить текущий `completed_at -> closed_at` mapping и complete
   UTC window filtering.
3. Собрать вторую сопоставимую CI window, retry/flaky examples и достаточный
   multi-repository cohort; DORA оставить `NOT_APPLICABLE`, пока не появятся
   deployment/environment/incident events.
4. Повторить correlation, sensitivity и counterfactual checks на объединённом
   controlled + real cohort.
5. Только после этого принимать решение о freeze weights, `K` thresholds и
   security caps; Score Engine до этого не менять.
