# Repo Health architecture

The supported runtime is a modular monolith with a real worker boundary.
`repo-health-api` accepts a versioned `AnalysisRequest`; the orchestrator
collects `RepositoryFacts`, schedules six isolated analyzers, sends their
`CategoryResult` values to the frozen score engine, and persists one immutable
analysis envelope.

The local executor runs the same serialized task contract in-process. The
worker entry point (`repowise-health-worker`) uses a replaceable queue port and
database-backed leases. Redis, Kafka, Kubernetes and six mandatory network
services are intentionally not required.

Boundaries and dependency direction are documented in
[architecture-target.md](architecture-target.md). The implementation lives
under `packages/core/src/repowise/core/repo_health`; analyzer modules may only
consume versioned contracts and normalized facts. API, ORM and raw SourceCraft
payloads do not cross into analyzer business logic.

See also: [deployment](deployment.md), [development](development.md),
[scoring](scoring.md), and the [archive evidence](research/archive/README.md).
