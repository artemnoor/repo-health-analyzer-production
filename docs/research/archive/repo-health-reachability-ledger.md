# Repo Health reachability and cleanup ledger

This ledger is the Phase 1 deletion evidence. It is intentionally conservative:
`candidate-delete` is not a safe-to-delete decision. The proof gate remains
static references = zero, runtime/entry-point reachability = zero,
package/config/script references = zero, migrated tests, golden/API parity,
legal inventory and a reversible deletion commit.

Evidence classes used below are `static reference`, `import-time registration`,
`runtime invocation`, `test/fixture-only reference`, `docs/research reference`
and `packaging/license reference`.

| path | current purpose | keep/move/delete/archive | reason | risk | verification | runtime references | test references | package references | license/notice action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `packages/core/src/repowise/core/analysis/health/integrations/__init__.py` | import-time bootstrap for 19 IDs | move/split | mixes six target paths with auxiliary and legacy adapters | hidden registration or ID drift | six-ID registry contract plus clean import smoke | `register_all_health_adapters`, package import | `test_analyzer_registry.py`, lightweight imports | public health integration exports | retain compatibility notices until split is released |
| `health/integrations/chaoss_adapter.py` | CollectOSS/CHAOSS/Graal facts and four registered IDs | split; no delete yet | activity/issues behavior and lazy vendor bridges share one file | losing activity/issues parity or GPL obligations | normalized fixture replay and per-source reachability | bootstrap, `ChaossAdapter`, activity/issues verification scripts | activity/issues/forge tests | package exports and config IDs | inventory each copied subtree and preserve GPL notices |
| `health/integrations/activity_analyzer.py` + `pydriller_adapter.py` | PyDriller/Git activity behavior | keep, then move behind `repo-health.activity` | frozen Activity baseline is production evidence | score/evidence/coverage drift | PyDriller golden and calibration-v2 parity | orchestrator/registry compatibility path | `test_activity_analyzer_pydriller.py`, integration smoke | PyDriller dependency and config | keep PyDriller attribution and source pin |
| `health/integrations/issues_analyzer.py` + `issues_facts.py` | issues normalization, findings and partial policy | keep, then move behind `repo-health.issues` | current SourceCraft/CollectOSS-shaped behavior is required | missing data becoming zero | rich/no-issue/malformed/partial fixtures | `chaoss.issues_prs` adapter and issues verification | unit/integration issues tests | `config/analyzers/issues.yaml` | preserve source and metric notices |
| `health/integrations/cicd_analyzer.py` + `cicd_facts.py` | SourceCraft CI normalization and calibrated score | keep, then move behind `repo-health.cicd` | calibration-v2 is frozen | status/pagination/retry drift | CI fixture verification and policy digest | `cicd.sourcecraft` registration and script | CI unit/integration/golden tests | `config/analyzers/cicd.yaml` | no copied provider source; retain API attribution |
| `health/integrations/appsec_analyzer.py` + `appsec_adapter.py` | SourceCraft AppSec REST boundary | keep, then move behind `repo-health.security` | explicit REST-only production path | raw payload leak or security cap change | malformed/unavailable/redaction and score-cap tests | `sourcecraft.appsec` registration | AppSec adapter/analyzer tests | `config/analyzers/appsec.yaml` | provider terms stay in integration docs |
| `health/integrations/code_health_analyzer.py`, `code_health_collector.py`, `sonarqube_adapter.py`, `git_sizer_adapter.py`, `todo_debt_adapter.py` | SonarQube/git-sizer/Git/TODO facts | keep, then move behind `repo-health.code-health` | current implementation is the target replacement for broad health | losing file-level Code Health behavior | code-health fixtures plus old/new replay | integration orchestrator and health compatibility edge | code health unit tests | `config/analyzers/code-health.yaml` | external tools remain adapter/process dependencies |
| `health/integrations/contracts.py` | compatibility re-export of neutral contracts | keep temporarily, then move | existing callers still import health edge | premature import break | import graph and JSON contract parity | health package public exports | integration core compatibility tests | package API imports | no third-party source |
| `health/integrations/orchestrator.py` + `runner.py` | current health execution/composition edge | move behind orchestrator boundary | execution exists but is not Repo Health task/queue model | retry/partial failure regression | serialized task parity and failure-isolation tests | registry, score engine and context | analyzer integration core/parity tests | core package exports | no special notice |
| `health/score_engine_v1.py` | frozen six-category Score v1 and default selection | keep canonical | weights/K/security caps are source of truth | formula drift | golden, config digest and parity scripts | persistence envelope and orchestrator | score v1 and parity tests | `config/analyzers/repo-health-score-v1.yaml` | no copied code deletion |
| `health/composite.py` | legacy eight-dimension score | keep behind compatibility; delete only later | callers exist in persistence, scripts and tests | persisted/API score replay changes | caller ledger, dual-run and legacy replay | health envelope, Vale verification, integration paths | composite, Vale, issues and parity tests | legacy `health-score.yaml` | retain historical methodology references |
| `health/scoring.py:score_file` | file-level biomarker scoring | keep | Code Health and historical fixtures use it | confusing repo/file scopes | existing scoring snapshots and scope tests | `engine.py`, history refresh, projections | scoring and performance tests | core health package | no external notice |
| `persistence/crud/analysis/health_envelope.py` | calculate and persist health envelopes | split into score port + persistence adapter | direct score dependency crosses boundary | projection or replay drift | persistence integration and stored digest tests | server/CLI/MCP read paths and ORM models | persistence/server canonical tests | Alembic models and migrations | database schema history retained |
| `server/job_executor.py` | broader RepoWise background jobs | keep; add separate Repo Health task namespace | not a durable analyzer queue | mixing job semantics | coexistence, idempotency and retry tests | repos/jobs/pages routes | server jobs tests | `pipeline_jobs`/JobStore | no external notice |
| `server/routers/health.py`, `public_health.py`, `code_health/*` | public health HTTP projections | keep; move to read port | public response compatibility is protected | API shape regression | API golden/e2e and projection tests | `create_app` mounts routers | server canonical score/health tests | FastAPI package | no external notice |
| `server/mcp_server/tool_health.py` | MCP health serialization and ORM reads | move to read service | bypasses canonical persistence/API projection | MCP payload regression | MCP golden and response-size tests | MCP bootstrap | MCP health tests | server package | no external notice |
| `cli/commands/health_cmd/*` | CLI health execution/render/persistence | keep; adapt to contracts | public CLI is protected | output/exit-code drift | CLI fixture and smoke tests | CLI command registry | CLI health tests | project scripts entry point | no external notice |
| `config/analyzers/repo-health-score-v1.yaml` | frozen v1 policy | keep, contract-owned | formula/config source of truth | code/config divergence | policy digest and golden score | score engine loader | score tests | package/config loader | no external notice |
| `config/analyzers/health-score.yaml` | legacy eight-dimension policy | keep until caller/replay zero, then archive/delete | legacy composite still resolves it | old persisted result unreadable | full string search plus legacy replay | `composite.py` fallback | composite/parity tests | config loader | archive methodology; do not remove attribution |
| `config/analyzers/native-tools.yaml`, `metrics.yaml`, `forge.yaml` | optional/native/legacy provider policies | move to compatibility/auxiliary config | current bootstrap advertises 19 paths | broader RepoWise feature regression | clean bootstrap and config loading audit | native/CHAOSS/forge adapters | native and enrichment tests | config discovery | preserve notices for retained engines |
| `vendor/scorecard`, `repohealth`, `criticality_score`, `qlty`, `sokrates` | copied optional/native tools | candidate-delete from Repo Health; not yet delete | target six analyzers do not require them | hidden CLI/ranking consumers | whole-repo reachability, native golden and build audit | registry IDs/configs/scripts | native health tests | `vendor/SOURCES.lock` and build scripts | restore/parse source roots before legal decision |
| `vendor/sonarqube` | copied SonarQube source/primitives | candidate-delete after adapter audit | target uses external SonarQube service | hidden parser/build dependency | adapter, package and source search | Sonar adapter only is unproven until audit | code health tests | `SOURCES.lock` and vendor notices | preserve Sonar licenses/notices until removal proof |
| `vendor/collectoss`, `vendor/chaoss/*` | copied metric, identity and external analyzer trees | conditional move/delete | current adapters still mention copied CollectOSS/SortingHat/Graal behavior | activity/issues drift and GPL obligations | direct normalized collector replay and per-subtree search | lazy imports and compatibility adapters | activity/issues/identity/forge tests | source ledger and package build | inventory every nested LICENSE/NOTICE; never bulk delete |
| `vendor/repocrunch` | Forge/dependency source bridge | conditional keep outside Repo Health | may serve wider RepoWise features | metadata/dependency regression | whole-repo import and API audit | dependency/forge adapter | enrichment tests | source ledger | retain license if wider feature remains |
| `vendor/documentor`, `vendor/lychee` | copied documentation/link-checker spikes | candidate-delete after reference audit | no target analyzer imports them | hidden script/reference or notice loss | docs/scripts search, package manifest and notice audit | no verified production path | spike/integration fixtures only | source ledger | preserve Apache/NOTICE and MIT/Apache notices until removal |
| `spikes/*/runs`, `$out/` | generated live JSON/CSV/log output | archive selected redacted evidence; local-only/delete generated runs | never package generated state | deleting user-owned evidence | ownership check, redaction and package ignore test | none proven | replay fixtures may derive from selected files | package manifests must exclude | keep only required attribution/notice files |
| Doc Detective, Schemathesis, Hercules, OpenDigger | named research/spike references | archive reference or delete local copy if found | scoped search found no source/binary in packages/config/scripts/tests | losing methodology provenance | exact scoped search and archive index | none found | none found | none found | no local license found; record “not found after scoped search” |
| DevLake | CI methodology reference | keep as docs-only reference for now | appears only in `config/analyzers/cicd.yaml` methodology text | mistaken runtime assumption | config/runtime search and CI fixture tests | no runtime import found | no fixture implementation found | no package source | no copied license found |

## Score-path trace

The current trace is explicit:

`server/routers + CLI/MCP` → `health/integrations/orchestrator.py` and
`persistence/crud/analysis/health_envelope.py` →
`compose_default_repo_health_score` → either frozen
`compose_repo_health_score_v1` or the legacy `compose_health_score` fallback.

`score_file` is a separate file-level Code Health path used by
`health/engine.py` and `history_refresh.py`; it must not be confused with the
repo-level Score v1 engine. The legacy path is therefore KEEP/compatibility,
not DELETE, until replay and persisted-result migration are complete.

## Safe deletion proof command set

Before any physical deletion, run the candidate-specific searches plus:

```text
rg -n "compose_health_score|compose_default_repo_health_score|compose_repo_health_score_v1|registry.register|import_module|SOURCES.lock" packages tests scripts config docs
uv run pytest -q tests/unit/health/test_analyzer_integration_parity.py tests/unit/health/test_repo_health_score_v1.py
uv run python scripts/vendor_sources.py --verify
```

Unknown dynamic imports, reflection, executable discovery and missing source
roots remain **unproven**. A failed or unavailable verification downgrades a
candidate to KEEP/MOVE; it never authorizes DELETE.
