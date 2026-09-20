# Repo Health audit baseline

This is the reproducible Phase 1 baseline for the production cleanup. It is
evidence, not a deletion authorization. The machine-readable record is
[repo-health-audit-baseline.json](repo-health-audit-baseline.json).

## Run identity

The baseline was captured at revision `7abe0d66cf2863d9a2dfb514e6e9e5c3e63e86b3`
on branch `module/extract-analyzer-integration-core-5865c9`. The worktree still
contains the pre-existing `$out/` and `spikes/` paths. They were not reset,
staged or deleted. No provider tokens or raw live payloads were recorded.

Commands and tool versions are in the JSON ledger. The two important graph
artifacts are ignored by the package:

- `packages/core/src/graphify-out/graph.json` — Graphify AST graph;
- `packages/core/src/graphify-out/static-import-graph.json` — deterministic
  local-module import graph.

## Graph evidence

`graphify packages/core/src --no-viz --directed --code-only` found 934 code
files, skipped 13 non-code files and 52 unsupported template/data files, and
produced 14,555 nodes with 33,865 links. Endpoint validation found zero missing
endpoints, self-loops or duplicate relation edges. Graphify is structural
evidence only: dynamic imports, plugin discovery and runtime calls require the
separate registry and entry-point checks.

The AST import scan covered 1,344 Python modules and produced 1,863
deduplicated local-module edges. A previous symbol-level scan recorded 4,259
local import edges; these numbers are intentionally not conflated because the
scans use different edge granularity.

## Registry and category ownership

The clean-process import of
`repowise.core.analysis.health.integrations` registered exactly 19 IDs. The
full ID list and the explicit six-category mapping are in the JSON ledger and
the current architecture document. The current bootstrap is broader than the
target boundary:

| target category | current registered path | planned canonical ID | classification at baseline |
| --- | --- | --- | --- |
| Documentation | `vale.documentation` | `repo-health.documentation` | target candidate |
| Activity | `chaoss.activity` | `repo-health.activity` | PyDriller/Git behavior must be preserved behind migration |
| Issues | `chaoss.issues_prs` | `repo-health.issues` | target candidate with partial-component policy |
| CI/CD | `cicd.sourcecraft` | `repo-health.cicd` | target candidate |
| Security | `sourcecraft.appsec` | `repo-health.security` | target candidate |
| Code Health | broad `repowise.health` plus optional native paths | `repo-health.code-health` | not yet a single canonical registry entry |

The remaining 13 IDs are auxiliary, compatibility, enrichment or optional
external-tool registrations. A static zero or a registry absence is not proof
that one is removable.

## Entry-point and ownership inventory

| area | exact path/symbol | incoming boundary | outgoing dependencies | runtime classification |
| --- | --- | --- | --- | --- |
| API | `server/app.py:create_app` | process startup | FastAPI routers, settings | runtime entry point |
| health API | `server/routers/health.py:router` | `create_app` | services, persistence/read models | runtime invocation |
| public health | `server/routers/public_health.py:router` | `create_app` | health ranking projections | runtime invocation |
| code health API | `server/routers/code_health/canonical_routes.py:router` | code-health router | health persistence/read model | runtime invocation |
| job orchestration | `server/job_executor.py` | jobs/repos/pages routes | broader RepoWise pipeline and `JobStore` | runtime invocation; not yet Repo Health queue |
| MCP | `server/mcp_server/_server.py` | MCP router/CLI | MCP tool modules and persistence | runtime entry point |
| MCP health | `server/mcp_server/tool_health.py` | MCP registration | ORM/read models and health serializers | runtime invocation |
| CLI health | `cli/commands/health_cmd/command.py:health_command` | CLI command registry | health integration runner, persistence | runtime entry point |
| CLI batch | `cli/commands/health_cmd/batch.py:health_batch_command` | CLI command registry | analyzer context/registry | runtime entry point |
| analyzer bootstrap | `health/integrations/__init__.py:register_all_health_adapters` | import-time side effect | 19 adapter factories | import-time registration |
| score v1 | `health/score_engine_v1.py:compose_repo_health_score_v1` | health envelope/verification | six category results and frozen policy | runtime invocation |
| legacy score | `health/composite.py:compose_health_score`, `compose_default_repo_health_score` | compatibility fallback | legacy health rows/config | runtime invocation; deletion unproven |

The complete module-level incoming/outgoing counts are in the ignored static
import graph. The graph is navigation evidence; DELETE decisions additionally
require string/config/manifest searches, clean bootstrap, tests, replay and
license proof.

## Verification outcome

- `compileall` for core/server/CLI passed;
- analyzer registry and lightweight health imports passed: 14 tests;
- `vendor/SOURCES.lock` verification failed closed because the 17 referenced
  `.sources/*` roots are absent in this checkout. The two reference-only rows,
  `codescene-product-reference` and `repohealth-tools-product-reference`, and
  the present `lychee`/`documentor` trees were not silently treated as verified;
- no product behavior was changed by this task.

The failed vendor verification is a Phase 1 finding. It blocks the legal
freeze/deletion phase until source provenance and notices are restored or the
ledger is explicitly reconciled.
