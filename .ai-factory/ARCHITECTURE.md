# Target architecture map

## Runtime tree

| Area | Responsibility |
| --- | --- |
| `src/repo_health/contracts` | Versioned transport-neutral request, facts, result, execution, and score schemas |
| `src/repo_health/collection` | SourceCraft, Git, PyDriller, Vale, SonarQube, git-sizer, cache, and normalized facts |
| `src/repo_health/analyzers` | Six independent analyzer boundaries and serialized worker harness |
| `src/repo_health/scoring` | Frozen Repo Health Score v1 and pure calibration-v2 policy ports |
| `src/repo_health/orchestration` | Collection, execution, partial failure, idempotency, and result composition |
| `src/repo_health/execution` | Local bounded executor and durable worker executor |
| `src/repo_health/persistence` | Repository/analysis/task state and immutable result storage |
| `src/repo_health/api` | REST transport and lifecycle endpoints only |
| `tests` | Unit, contract, adapter, integration, golden, and end-to-end gates |
| `docs` | Current product, operations, API, and concise methodology documentation |

## Canonical flow

`AnalysisRequest → collection → RepositoryFacts → analyzer executor → six
CategoryResult values → ScoreEngineV1 → RepoHealthResult → persistence/API`

The local and worker execution modes serialize the same `AnalyzerInput` and
`CategoryResult` contracts. A worker can therefore move to another process or a
queue without changing analyzer business logic.

## Dependency direction

`api → orchestration → execution/collection/persistence → contracts`

`analyzers → contracts + analyzer-specific facts/policy`

`scoring → contracts`

`adapters → external tools + contracts`

Contracts never import FastAPI, ORM/database implementations, provider payloads,
or analyzer internals. Analyzers never import another analyzer. API code never
calculates scores directly.

## Deliberate deployment shape

The production baseline is one API process with a scheduler and a worker
execution abstraction. `LocalExecutor` is the low-overhead development mode;
`WorkerExecutor` supplies durable task claims, leases, retries, timeouts, and
idempotency. Separate network services, Kafka, Redis, Kubernetes, and service
mesh remain future deployment options, not current product dependencies.
