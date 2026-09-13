# Current architecture map

## Repository shape

| Area | Responsibility |
| --- | --- |
| `packages/core` | Core repository analysis, ingestion, facts, scoring, health projections, and domain contracts |
| `packages/server` | Python API/server orchestration and persistence-facing boundaries |
| `packages/cli` | CLI entry points and command workflows |
| `packages/types` | Shared typed contracts for the JavaScript/TypeScript surfaces |
| `packages/api-client` | Client-side API contract helpers |
| `packages/web` | Next.js web UI and public health/ranking surfaces |
| `packages/ui` | Reusable UI components |
| `packages/vscode` | VS Code integration surface |
| `tests` | Unit, integration, regression, fixture, and contract coverage |
| `scripts` | Verification and developer/setup automation |
| `vendor` | External source snapshots or vendored tools; do not treat them as application-owned modules |
| `docs` | Product, architecture, API, testing, and operational documentation |

## Important data flow

An analyzed checkout flows through ingestion and analyzers into persisted raw
facts, canonical health projections, and explainable reports. API, CLI, MCP, and
UI consumers should use the same canonical score/report contract rather than
reimplementing scoring independently.

The report distinguishes measured negative results from `unavailable`, `skipped`,
or `inconclusive` measurements. Evidence and limitations are first-class output.

## Modularization direction

Future extraction should introduce explicit contracts around analyzer context,
definitions, results, statuses, findings, evidence references, metric values,
limitations, registry, runner, orchestrator, lifecycle, and process boundaries.

External projects should be accessed through replaceable engines, adapters, or
providers. The old working path remains the comparison baseline during migration.

## Change boundaries

Do not change product packages as part of infrastructure setup. For future module
tasks, restrict the diff to the selected module and its tests/docs/configuration;
preserve unrelated APIs, UI, scoring, and vendor contents.
