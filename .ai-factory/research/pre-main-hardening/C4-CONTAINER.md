# C4 Container View: Repository Health Analyzer hardening

Research: [INDEX.md](INDEX.md)
Parent context: [C4-CONTEXT.md](C4-CONTEXT.md)

## Diagram
```mermaid
flowchart LR
    api["Container: API"] -->|AnalysisRequest| orch["Container: Orchestrator"]
    worker["Container: Worker"] -->|same request/result contracts| orch
    orch -->|profile-aware collection| collect["Container: Collection adapters"]
    collect -->|RepositoryFacts| analyzers["Container: Six analyzers"]
    analyzers -->|CategoryResult[]| score["Container: ScoreEngineV1"]
    score -->|RepoHealthResult| store[("Container: SQLite / JSON persistence")]
    collect -->|PAT only for OWNER_EXTENDED| sc["External: SourceCraft"]
```

## Containers

| Container | Technology | Responsibility | Data owned | Evidence |
|-----------|------------|----------------|------------|----------|
| API | FastAPI | Transport, health/readiness, request DTOs, background scheduling | HTTP DTOs only | `src/repo_health/api/app.py` |
| Worker | Python process | Durable execution of the same queued contracts | task lifecycle only | `src/repo_health/worker.py`, `src/repo_health/execution` |
| Orchestrator | Python service | Collection → analyzer dispatch → score → envelope | lifecycle composition | `src/repo_health/orchestration/orchestrator.py` |
| Collection adapters | Python/httpx/process/library adapters | Normalize Git, SourceCraft, Vale, Sonar, git-sizer facts | `RepositoryFacts` | `src/repo_health/collection` |
| Six analyzers | Python pure policy modules | Produce independent CategoryResult values | category semantics | `src/repo_health/analyzers` |
| ScoreEngineV1 | Pure Python | Apply frozen formula and caps once | RepoHealthResult score fields | `src/repo_health/scoring/v1.py` |
| Persistence | SQLite + Pydantic JSON | Store redacted request/facts/results and worker tasks | immutable envelopes | `src/repo_health/persistence` |

## Relationships

| From | To | Interaction / data | Failure concern | Evidence |
|------|----|--------------------|-----------------|----------|
| API | Orchestrator | request with profile and safe auth metadata | untrusted DTO validation | `src/repo_health/api/app.py` |
| Worker | Orchestrator | persisted task/replay contracts | parity drift | `src/repo_health/execution` |
| Orchestrator | Collection adapters | profile-aware collection context | public accidentally consumes owner data | `src/repo_health/collection/service.py` |
| Collection adapters | Analyzers | normalized facts only | raw payload or credential leakage | `.ai-factory/RULES.md` |
| Analyzers | ScoreEngineV1 | CategoryResult[] | formula duplication | `src/repo_health/scoring/v1.py` |
| ScoreEngineV1 | Persistence | redacted result envelope | metadata serialization drift | `src/repo_health/persistence/sqlite.py` |
