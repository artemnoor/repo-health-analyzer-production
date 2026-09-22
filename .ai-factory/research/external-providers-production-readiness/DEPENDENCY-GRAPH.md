# Runtime Dependency Graph

```mermaid
flowchart TD
    API[REST API] --> ROOT[Production composition root]
    WORKER[Worker / scheduler] --> ROOT
    ROOT --> CFG[RuntimeConfig + capability detection]
    ROOT --> COL[CollectionService]
    ROOT --> EXEC[LocalExecutor / WorkerExecutor]
    ROOT --> PERSIST[SQLitePersistence]

    COL --> GIT[GitCollector]
    COL --> PYD[PyDrillerCollector]
    COL --> VALE[ValeCollector]
    COL --> TODO[TODO/history collector]
    COL --> SIZER[git-sizer collector]
    COL --> SONAR[SonarQube REST collector]
    COL --> SC[Shared SourceCraftClient]
    SC --> ISSUES[SourceCraft Issues adapter]
    SC --> CICD[SourceCraft CI/CD adapter]
    SC --> APPSEC[SourceCraft AppSec adapter]

    GIT --> FACTS[RepositoryFacts]
    PYD --> FACTS
    VALE --> FACTS
    TODO --> FACTS
    SIZER --> FACTS
    SONAR --> FACTS
    ISSUES --> FACTS
    CICD --> FACTS
    APPSEC --> FACTS

    FACTS --> ANALYZERS[Six isolated analyzers]
    ANALYZERS --> SCORE[ScoreEngineV1]
    SCORE --> PERSIST
```

## Direction rules

- API, worker, and scheduler depend on the composition root, never on provider
  internals.
- External providers depend on `SourceCraftClient` or process/HTTP boundaries;
  they do not depend on FastAPI, persistence, or analyzers.
- Providers emit only normalized `RepositoryFacts`.
- Analyzers consume contracts and policy modules; no analyzer imports another
  analyzer's internals.
- Score Engine v1 consumes category results and remains unchanged.
- Persistence stores result contracts only; credentials and raw provider
  payloads are excluded.

## Boundary risk

The only current runtime substitution is the explicit unavailable Issues/CI/CD
placeholder in `runtime.py`. Replacing it with official adapters is therefore
low-risk if the provider-to-facts mapping is contract-tested and the existing
golden analyzer tests remain unchanged.
