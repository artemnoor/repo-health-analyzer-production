# Scoring and recommendations

[← Previous](getting-started.md) · [Back to README](../../README.md) · [Next →](architecture.md)

## Каноническая формула

Каждое доступное dimension получает нормализованный score `sᵢ` в диапазоне
`0..100`. Итог считается как weighted mean только по доступным dimensions:

```text
Repo Health Score = Σ(weightᵢ × sᵢ) / Σ(weightᵢ),
                    только для измеренных dimensions
```

Если dimension не имеет usable evidence, её значение — `null`, а её weight
исключается из знаменателя. Это делает результат честным при частично доступных
анализаторах. Если не измерено ничего, итоговый score отсутствует (`null`).

## Dimensions и веса по умолчанию

| Dimension | Weight | Что отвечает |
| --- | ---: | --- |
| `code` | 0.25 | структура, maintainability и дефекты code shape |
| `history` | 0.15 | churn, activity и исторический сигнал риска |
| `tests` | 0.15 | тестовые сигналы и coverage evidence |
| `dependencies` | 0.10 | состояние dependency graph и зависимостей |
| `security` | 0.15 | security checks и связанные findings |
| `delivery` | 0.10 | CI/CD и delivery hygiene |
| `community` | 0.05 | активность и признаки сообщества |
| `docs` | 0.05 | документация и repository hygiene |

Реальная политика сериализуется и получает `score_config_digest`. Поэтому
snapshot, replay, rescore, API, CLI и UI могут показать, какой именно policy
создал число.

## Score не равен confidence

| Поле | Смысл |
| --- | --- |
| `overall_score` | насколько здоровым выглядит измеренная часть репозитория |
| `coverage` | сколько configured weight было доступно |
| `evidence_coverage` | насколько доступные данные подтверждены evidence |
| `confidence` | уверенность в агрегированном результате |
| `status` | `pass`, `warn`, `fail`, `skipped`, `inconclusive` или `error` |

Высокий score с низким evidence coverage не должен автоматически попадать в
публичный рейтинг. По умолчанию ranking требует не менее `0.5` evidence coverage.

## Bands и оценки

| Score | Band | Grade |
| ---: | --- | --- |
| 90–100 | `excellent` | A |
| 80–<90 | `good` | B |
| 70–<80 | `fair` | C |
| 60–<70 | `weak` | D |
| 0–<60 | `critical` | F |
| нет score | `unknown` | — |

`0` — валидный измеренный score. `null` — отсутствие пригодного canonical
projection. `stale`, `warn` и `inconclusive` не превращаются в здоровый ноль и
не скрываются в UI.

## Vale как дополнительный docs source

Vale выдаёт отдельный `AnalyzerResult` с `score_dimension=docs`. Existing
completeness checks не удаляются и не переписываются. В частности, наличие
README/LICENSE/CONTRIBUTING/CODEOWNERS и run/build/test instructions продолжает
измеряться baseline analyzer.

Внутри Vale score используется bounded density, а не прямое число warnings:

```text
word_denominator = max(words, analyzed_files × 20)
weighted_points = Σ severity_weight(finding)
density = weighted_points / word_denominator
penalty = min(30, density × 40)
vale_quality = 100 - penalty
```

Severity weights policy: suggestion `0.25`, warning `1`, error `2`, fatal `3`.
Сама scored metric `vale_quality` имеет `denominator=1`: размер и coverage
документации используются для нормализации качества внутри Vale, но число слов
или findings не получает непропорциональный вес в общем composer. Поэтому Vale
добавляет один объяснимый docs contribution и не может линейно обнулить Repo
Health score большим количеством предупреждений. `vale_coverage`,
`vale_metrics_coverage`, finding density и prose metrics сохраняются как
не-scored evidence.

Состояния источника различаются явно:

| Состояние | Result status | Score contribution |
| --- | --- | --- |
| качественный текст | `pass` | quality score доступен |
| warning/error findings | `warn`/`fail` | bounded quality score доступен |
| Vale отсутствует | `skipped` + `missing_capability` | отсутствует |
| timeout, malformed JSON, process failure | `error` | отсутствует |
| подходящие documentation files отсутствуют | `inconclusive` + `insufficient_denominator` | отсутствует |

Таким образом, `skipped`, `error` и отсутствие denominator не маскируются под
`0`; composer учитывает только evidence-backed score и добавляет limitation.

## Почему рекомендации объяснимы

Recommendation хранится рядом с snapshot и связывает finding с:

- dimension и severity;
- subject/location, где можно начать исправление;
- remediation — конкретным действием;
- evidence и limitation, если источник неполный;
- priority context от criticality.

Criticality отвечает на вопрос «что исправлять первым из опасного», но не
штрафует сам score. Иначе большой blast radius мог бы незаметно смешаться с
качеством кода.

## Что подтверждает формулу

| Утверждение | Подтверждение |
| --- | --- |
| веса и weighted mean | [`composite.py`](../../packages/core/src/repowise/core/analysis/health/composite.py) |
| `0..100`, missing dimensions и limitations | [`test_score_invariants.py`](../../tests/unit/health/test_score_invariants.py) и [`test_health_score_projection.py`](../../tests/unit/persistence/test_health_score_projection.py) |
| canonical score во всех поверхностях | [`test_health_canonical_contract.py`](../../tests/unit/cli/test_health_canonical_contract.py) и [`test_health_canonical_score.py`](../../tests/unit/server/test_health_canonical_score.py) |
| bands, freshness и evidence eligibility | [`ranking_projection.py`](../../packages/core/src/repowise/core/analysis/health/ranking_projection.py) и [`test_score_invariants.py`](../../tests/unit/health/test_score_invariants.py) |

## See Also

- [Architecture](architecture.md) — где score сохраняется и читается.
- [API](api.md) — как получить breakdown и recommendations.
- [Getting started](getting-started.md) — первый запуск анализа.
