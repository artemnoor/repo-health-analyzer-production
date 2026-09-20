# Документация Repository Health Analyzer

Этот раздел описывает именно сервис оценки здоровья открытых репозиториев:
его пользовательский поток, контракт score, API, публичный рейтинг и
подтверждение работоспособности. Текущая папка также содержит исторические
страницы более широкого codebase-продукта; они не являются источником истины
для Repo Health Score.

## Основной путь

| Страница | Когда читать |
| --- | --- |
| [Getting started](repository-health/getting-started.md) | Нужно запустить анализ и открыть результат |
| [Scoring](repository-health/scoring.md) | Нужно понять, откуда взялось число |
| [Architecture](repository-health/architecture.md) | Нужно разобраться в pipeline и хранении |
| [API](repository-health/api.md) | Нужно подключить свой клиент или страницу |
| [Testing](repository-health/testing.md) | Нужно проверить релиз или локальную сборку |

## Repo Health backend cleanup

The current production-oriented surface is intentionally small:

- [Architecture](architecture.md) and [target architecture](architecture-target.md);
- [Scoring](scoring.md);
- [Analyzer boundaries](analyzers/README.md);
- [SourceCraft integration](sourcecraft-integration.md);
- [Deployment](deployment.md) and [development](development.md);
- [Research and legal archive](research/archive/README.md).

## Канонические compatibility references

- [Health Analyzer reference](reference/HEALTH_ANALYZER.md) — короткий индекс
  старого пути ссылки и обязательные release/checkpoint semantics.
- [Repository health architecture](architecture/repository-health.md) —
  compatibility entry point для существующих ссылок.
- [Native tools](reference/NATIVE_TOOLS.md) — pinned источники и provenance
  внешних анализаторов.

## Остальные материалы

Документы в `docs/start`, `docs/agent`, `docs/layers`, `docs/scale` и
`docs/business` описывают унаследованные возможности workspace. Для реализации
или проверки Repo Health Analyzer сначала используйте пять страниц выше; если
страница старого раздела говорит о другой шкале или другом продукте, приоритет
имеет canonical contract в [Scoring](repository-health/scoring.md).

## See Also

- [Корневой README](../README.md) — краткий вход в проект.
- [Roadmap](../ROADMAP.md) — границы и следующие этапы.
- [Health testing](repository-health/testing.md) — проверяемые команды и QA evidence.
