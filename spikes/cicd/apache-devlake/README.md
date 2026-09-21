# Apache DevLake spike

Verdict: **PARTIAL FIT; LIVE RUN BLOCKED BY THE ENVIRONMENT AND FIXTURE SHAPE**.

DevLake is a full dev-data platform, not a local analyzer binary. It ingests
CI/CD, code, issue, review, and quality data into raw/tool/domain layers,
exposes REST/plugin APIs, and serves SQL-backed Grafana dashboards. It is a
strong architectural match for build trends and DORA, but it requires a
database, containers, and an external data source or webhook stream.

## Source and license

- Upstream: `https://github.com/apache/devlake.git`
- Cloned at: `e744aefe04473062d1da46934da256aad8112add`
- License: Apache-2.0 (`upstream/LICENSE`, `upstream/NOTICE`, and README)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Standard setup and run evidence

The upstream README points to Docker Compose or Helm. The repository's
development PostgreSQL compose file was inspected at
`upstream/docker-compose-dev-postgresql.yml`; it provisions PostgreSQL,
Grafana, the DevLake backend, config UI, and an auth proxy.

Observed environment checks:

```text
docker compose version -> Docker Compose version v2.34.0-desktop.1
docker compose -f upstream/docker-compose-dev-postgresql.yml config -> FAIL
  env file upstream/.env not found
Docker daemon probe (docker info, 5 s timeout) -> unresponsive
```

Evidence is in `runs/docker-compose-version.*`, `runs/compose-config.*`, and
`runs/docker-info-timeout.*`. The daemon probe was stopped after the bounded
timeout; no containers, volumes, or network state were created.

The fixture cannot fill the missing data source: it contains a SourceCraft CI
workflow configuration and inert audit files, not CI execution history or a
DevLake database snapshot. No live DevLake result is claimed.

## Data model and requested metrics

The exact source documents a three-layer model in `upstream/AGENTS.md`:

1. raw `_raw_*` tables retain source JSON for replay/debugging;
2. tool `_tool_*` tables retain source-specific normalized objects;
3. domain tables normalize data for cross-tool dashboards.

For CI/CD, `backend/core/models/domainlayer/devops/cicd_pipeline.go` and
`cicd_task.go` define `cicd_pipelines` and `cicd_tasks` with `result`, `status`,
`created_date`, `finished_date`, `duration_sec`, optional
`queued_duration_sec`, `environment`, and `cicd_scope_id`. Deployments and
deployment commits are separate domain tables.

The Grafana dashboard SQL provides concrete algorithms:

- Build/pipeline success rate: group pipeline IDs by the selected day/week/
  month bucket and calculate `SUM(result = 'SUCCESS') / COUNT(*)`. Non-success
  results are the denominator's failures/other outcomes.
- Build duration: `AVG(duration_sec)` for completed pipelines, usually exposed
  in minutes, grouped by the same time bucket. Some dashboards remove an
  incomplete current month.
- Trends: the dashboards bucket on `finished_date` (or deployment
  `created_date`) and expose the bucketed ratio/mean to Grafana.
- DORA: the `backend/plugins/dora/tasks` pipeline generates deployments from
  successful deployment tasks/pipelines, links deployment commits, and derives
  change lead time from first PR commit → PR creation/review/merge → successful
  production deployment. The source explicitly filters successful production
  deployment commits when building these links.

This model can support Build Success Rate, Build Duration, trends, deployment
frequency, lead time, change failure/incident linkage, and recovery time after
the relevant plugin data is ingested. It is not a pure formula library: the
collector, extractor, converter, migrations, project mapping, and dashboards
are part of the result.

## Webhooks and custom ingestion

The webhook plugin is a practical boundary for this repository. The connection
API exposes endpoints for posting issues, pull requests, CI/CD tasks,
deployments, and closing a pipeline. The generated endpoint descriptions in
`upstream/backend/plugins/webhook/api/connection.go` include:

```text
/rest/plugins/webhook/connections/{id}/cicd_tasks
/rest/plugins/webhook/connections/{id}/deployments
/rest/plugins/webhook/connections/{id}/cicd_pipeline/{pipelineName}/finish
```

The request models in the adjacent API files include timestamps, result,
environment, commit/repository IDs, and durations. For richer sources, DevLake
expects a plugin with collector → extractor → converter tasks and a domain
model; `backend/DevelopmentManual.md` describes the pattern and incremental
bookmarking.

## Integration boundary, runtime, and limitations

The analyzer would integrate through DevLake's REST API/webhook endpoints or
read its normalized SQL tables. A full run has database startup, migrations,
source API pagination, extraction/conversion, and dashboard queries; its cost
scales with the historical event volume and source API rate limits. A local
fixture-only run is not meaningful without CI events.

The important adoption costs are operational: Docker/Helm, PostgreSQL or
MySQL, Grafana, credentials/rate limits for source systems, and the need to
define project mappings. The bounded environment test proves the installation
boundary but not metric correctness; that requires a seeded DevLake database
or webhook replay fixture.
