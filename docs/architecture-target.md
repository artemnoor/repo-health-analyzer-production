# Repo Health backend — architecture audit and target design

Status: target architecture plus implementation evidence. Structural
migration is applied incrementally; score formulas and protected behavior
remain frozen.

Audit date: 2026-09-20

This document is the architecture source of truth for the cleanup plan in
.ai-factory/plans/repo-health-backend-architecture-cleanup/.

## Executive decision

The target is a modular monolith with a real worker/deployable boundary, not
six mandatory network services.

The first production shape is:

1. repo-health-api — FastAPI authentication, request validation and public DTOs.
2. analysis-orchestrator — run identity, planning, scheduling, retries,
   partial-failure policy and publication.
3. sourcecraft-collector — provider REST/API boundary plus local Git facts;
   it emits RepositoryFacts and never exposes provider payloads to analyzers.
4. six analyzer modules — Documentation, Activity, Issues, CI/CD, Security and
   Code Health. Each has an independent deployable/worker entry point, but the
   local executor may call the same application object in-process.
5. score-engine — the frozen Repo Health Score v1 policy and explicit
   calibration-v2 policies.
6. persistence — a port-owned repository for immutable analysis envelopes and
   read-model projections.

The production-ready minimum is one API process plus one analysis worker process
with a local queue adapter or a database-backed job table. A queue abstraction
is required, but Redis/Kafka/Kubernetes are not required by this refactor.

The six canonical analyzer IDs are repo-health.documentation,
repo-health.activity, repo-health.issues, repo-health.cicd,
repo-health.security and repo-health.code-health. Existing provider/legacy IDs
resolve one-way to these IDs at the health edge and cannot add duplicate
categories to ScoreInput.

Score v1 remains frozen. No weights, K thresholds, security caps or
calibration-v2 values may change during the structural migration. The legacy
composite score remains only behind a compatibility gate until replay/parity
evidence proves that its callers are migrated.

## Audit scope and evidence

The reproducible Phase 1 ledger is kept separately at
`docs/research/archive/repo-health-audit-baseline.md` with its machine-readable
counterpart `repo-health-audit-baseline.json`. It records the exact revision,
dirty paths, tool versions, module/entry-point inventory, registry IDs,
classification contract and verification failures. The ignored Graphify and
AST import outputs referenced by that ledger are navigation evidence only and
are not part of the production package.

Behavioral, score, public-projection and generated-artifact freeze data is in
`docs/research/archive/repo-health-behavior-baseline.json`. Copied-source
provenance and notice preservation is in
`docs/research/archive/repo-health-license-manifest.md`; the current legal
gate records the remaining `vendor/collectoss` content drift, not deletion
approval.

Inspected:

- packages/core, packages/server and packages/cli;
- health integrations, analyzers, facts and external-tool adapters;
- pipeline, persistence CRUD/models, server routes, MCP and CLI boundaries;
- config/analyzers, scripts, tests, fixtures, docs, spikes, vendor and
  vendor/SOURCES.lock;
- the existing neutral analyzer-integration kernel;
- a static Python import graph and a Graphify AST graph.

The worktree already contains unrelated product and AI Factory changes. The
audit did not reset, checkout, stage or overwrite them. The current branch is
module/extract-analyzer-integration-core-5865c9 and is treated as the task
branch for this plan; branch switching is deliberately deferred until a clean
implementation worktree is prepared.

Graph evidence:

- Graphify code-only scan of packages/core/src: 934 code files and 13
  non-code files skipped; 14,555 nodes and 33,865 links.
- Graphify diagnosis: no dangling, missing, self-loop, collapsed or duplicate
  edges.
- Top graph relations include calls, references, imports, contains, uses and
  inherits. The graph is useful for structure, but reachability claims still
  require runtime/entry-point evidence.
- Static Python import scan: 1,344 modules and 4,259 local import edges.
- Notable cross-layer edges include server routers to core.persistence,
  server MCP to core.persistence, CLI commands to core.persistence,
  core.analysis.health to core.ingestion, and the reverse
  core.persistence to core.analysis.health. These are the main boundary
  violations to remove.

## 1. CURRENT architecture

The repository is a broad RepoWise monolith. Repo Health is an integration
edge inside the monolith rather than a bounded backend subsystem.

~~~mermaid
flowchart TD
    Client[Web UI / CLI / MCP] --> API[FastAPI routers and schemas]
    API --> Pipeline[RepoWise pipeline and job executor]
    API --> DirectDB[(SQLAlchemy models and CRUD)]
    MCP[MCP health tools] --> DirectDB
    CLI[CLI health commands] --> DirectDB
    Pipeline --> Ingestion[local repository ingestion and Git index]
    Pipeline --> HealthEngine[legacy HealthAnalyzer]
    HealthEngine --> Biomarkers[biomarkers / complexity / dataflow / scoring]
    Pipeline --> HealthEdge[health integrations bootstrap]
    HealthEdge --> Kernel[neutral analyzer integration kernel]
    HealthEdge --> LegacyAdapters[RepoWise / CHAOSS / Forge / native / temporal / identity / dependency]
    HealthEdge --> SixPaths[Vale / PyDriller / CI / AppSec / Code Health / Issues]
    LegacyAdapters --> Inventory[dict-like context.inventory and raw provider-shaped rows]
    SixPaths --> Results[AnalyzerResult]
    Results --> ScoreV1[Repo Health Score v1]
    Results --> LegacyScore[legacy composite score fallback]
    ScoreV1 --> HealthEnvelope[health envelope persistence]
    LegacyScore --> HealthEnvelope
    HealthEnvelope --> DirectDB
~~~

### Current component map

| Area | Current location | Audit finding |
| --- | --- | --- |
| Public API | packages/server/src/repowise/server | Routes and services can import SQLAlchemy models/CRUD directly. |
| Job execution | packages/server/src/repowise/server/job_executor.py | Background asyncio task executes the broader RepoWise pipeline; no durable analyzer queue boundary. |
| Neutral kernel | packages/core/src/repowise/core/analysis/analyzer_integration | Useful registry, Pydantic result model, cache, subprocess and lifecycle primitives already exist. |
| Health edge | packages/core/src/repowise/core/analysis/health/integrations | Compatibility facades re-export kernel contracts and bootstrap 19 analyzer IDs on import. |
| Repository ingestion | packages/core/src/repowise/core/ingestion and packages/core/src/repowise/core/pipeline | Produces many internal objects and persisted rows, not one transport-neutral RepositoryFacts envelope. |
| Six-category score | packages/core/src/repowise/core/analysis/health/score_engine_v1.py | Frozen v1 exists and has explicit coverage/confidence/K/security-cap semantics. |
| Legacy score | packages/core/src/repowise/core/analysis/health/composite.py | Eight-dimension legacy composer remains reachable through the compatibility fallback. |
| Code health | packages/core/src/repowise/core/analysis/health/engine.py and health/scoring.py | Large legacy RepoWise analyzer with file-level biomarker/scoring behavior; must remain intact behind the Code Health boundary. |
| Persistence | packages/core/src/repowise/core/persistence and crud/analysis/health_envelope.py | Persistence knows concrete score classes and health internals; API read models know ORM classes. |
| External tools | packages/core/src/repowise/core/analysis/health/integrations and vendor | Multiple native and copied tools are bootstrapped alongside the six intended paths. |
| Configuration | config/analyzers | Contains canonical six-path policies plus legacy/optional native and copied-source policies. |
| Research | spikes, docs/category-score-calibration.md and related reports | Valuable evidence is mixed with generated runs and temporary material. |

### Registry reality

The import-time health bootstrap registers 19 IDs:

chaoss.activity, chaoss.dependencies, chaoss.issues_prs, chaoss.releases,
cicd.sourcecraft, criticality.importance, dependencies.enrichment,
events.temporal, forge.community, forge.metadata, graal.external_tools,
identity.enrichment, qlty.check, repohealth.baseline, repowise.health,
scorecard.local, sokrates.analysis, sourcecraft.appsec and
vale.documentation.

The target production score consumes six category results. The other registered
IDs are either source collectors, auxiliary context, legacy compatibility or
optional external engines. Treating all 19 as peer analyzers is the current
bounded-context failure.

### Existing contracts

The neutral kernel already provides:

- AnalyzerDefinition;
- AnalyzerContext;
- AnalyzerStatus;
- EvidenceRef;
- Finding and FindingLocation;
- Limitation;
- MetricValue;
- AnalyzerResult;
- CachePolicy and ports for process, cache, collection, composition,
  persistence, publication and checkpoints.

The current contract is not yet the requested public contract. AnalyzerContext
contains Path values and an open inventory dict. AnalyzerResult is not a
CategoryResult and does not carry a separate AnalysisRequest/RepositoryFacts
identity. Provider-specific facts can still arrive through context.inventory.

The target contract must wrap and version these primitives without changing
their behavior first. Compatibility aliases are permitted only at the health
edge, not in the analyzer packages.

## 2. TARGET architecture

### Logical deployment

~~~mermaid
flowchart LR
    API[repo-health-api] -->|AnalysisRequest v1| ORCH[analysis-orchestrator]
    ORCH -->|collect task| COL[sourcecraft-collector]
    COL -->|RepositoryFacts v1| ORCH
    ORCH -->|AnalyzerInput v1| D[documentation-analyzer]
    ORCH -->|AnalyzerInput v1| A[activity-analyzer]
    ORCH -->|AnalyzerInput v1| I[issues-analyzer]
    ORCH -->|AnalyzerInput v1| C[cicd-analyzer]
    ORCH -->|AnalyzerInput v1| S[security-analyzer]
    ORCH -->|AnalyzerInput v1| H[code-health-analyzer]
    D -->|CategoryResult v1| ORCH
    A -->|CategoryResult v1| ORCH
    I -->|CategoryResult v1| ORCH
    C -->|CategoryResult v1| ORCH
    S -->|CategoryResult v1| ORCH
    H -->|CategoryResult v1| ORCH
    ORCH -->|ScoreInput v1| SCORE[score-engine]
    SCORE -->|RepoHealthResult v1| ORCH
    ORCH -->|AnalysisEnvelope v1| STORE[persistence port]
    STORE --> DB[(SQL database / read models)]
    API -->|read-only DTOs| STORE
~~~

### Runtime variants

| Variant | Components | Use |
| --- | --- | --- |
| Local sync | API/CLI calls orchestrator; collector and analyzers in-process; FileCache | Development, fixtures and deterministic tests. |
| Single worker | API writes an analysis task; one worker claims it and runs the same analyzer entry points in-process | Hackathon/early production; durable status and restartability without a heavy queue. |
| Scalable worker pool | API, collector worker and analyzer worker pool behind a QueuePort; each analyzer can become a separate deployable | Later scale-out when repository size, provider rate limits or tenant isolation require it. |

Every variant consumes the same serialized contracts. The in-process executor
is an execution strategy, not a permission to import analyzer internals into
the API.

### Service and module boundaries

| Boundary | Owns | May depend on | Must not depend on |
| --- | --- | --- | --- |
| repo-health-api | auth, rate limits, request DTOs, response DTOs, read-model queries | contract package, orchestrator port, persistence read port | analyzer internals, ORM models, raw provider payloads |
| analysis-orchestrator | analysis ID, task plan, scheduling, retries, timeouts, status aggregation, publication | contracts, executor ports, score port, persistence ports, telemetry | FastAPI, provider SDKs, analyzer implementation modules |
| sourcecraft-collector | SourceCraft REST/API calls, local Git/PyDriller collection, secret handling, normalization | provider clients, local Git adapters, contract package | score formula, UI, DB schema |
| analyzer package | facts-to-category business logic, evidence, coverage/confidence, policy | facts contract, common contract types, its own adapters | FastAPI, DB, UI, other analyzer package, raw SourceCraft response |
| analyzer adapter | one external engine or provider transport; parse and validate output | process/http port, provider DTOs, facts contract | score engine and ORM |
| score-engine | v1 category selection, weights, K, security caps, score provenance | CategoryResult and ScoreInput contracts | provider clients, file system, API framework |
| persistence write adapter | immutable envelope, idempotent upsert, projection writes | persistence models and contracts | analyzer calculation logic |
| persistence read adapter | stable query/read models | ORM and public result models | analyzer internals and recalculation |
| worker entry point | task deserialization, resource limits, executor invocation | queue port, orchestrator, telemetry | public HTTP concerns |

Canonical ID and coexistence rules:

- the ownership manifest is the normative current-ID-to-canonical-ID mapping;
- aliases are one-way and are removed only after the replay/API parity gate;
- ScoreInput accepts exactly one CategoryResult for each of the six canonical
  category keys;
- Repo Health tasks use a distinct task type/queue namespace and status owner;
  the existing broader RepoWise job executor remains independently runnable
  throughout migration.

### Dependency direction

The permitted direction is:

contracts → facts ports → adapters/analyzers → executor → orchestrator →
score-engine/persistence ports → infrastructure/API projections.

API and CLI may depend on orchestrator ports and read ports. They may not
import ORM models, analyzer implementation classes or provider payload types.

Analyzer A may not import Analyzer B. Shared behavior belongs in contracts,
facts normalization or a deliberately small common library. If two analyzers
need the same source data, the collector publishes one normalized fact type.

## 3. Contract-first design

All contracts use JSON-compatible Pydantic models with:

- schema_version as a required integer or semantic version;
- extra="forbid" on published objects;
- deterministic serialization with sorted mapping keys and stable tuples;
- UTC timestamps and explicit repository HEAD;
- no absolute local paths in public payloads;
- redaction metadata for evidence;
- stable IDs derived from analysis ID, repository ref, analyzer ID, fact key and
  normalized content;
- backward-compatible additive evolution only within a major version;
- a contract test suite that validates JSON round-trip independently of imports.

### Required contracts

| Contract | Required fields | Invariants |
| --- | --- | --- |
| RepositoryRef | schema_version, repository_id, canonical_uri, provider, ref, head_sha, snapshot_id | canonical URI is redacted/normalized; head SHA identifies facts; local path is an internal capability, never serialized. |
| AnalysisRequest | schema_version, analysis_id, repository, requested_analyzers, mode, as_of, config_digest, idempotency_key | analysis_id and idempotency key are stable; requested analyzer IDs are sorted and deduplicated. |
| RepositoryFacts | schema_version, repository, source_snapshot_digest, git, sourcecraft, files, capabilities, limitations, collected_at | provider raw payloads are absent; every fact has provenance and availability; digest is deterministic. |
| AnalyzerInput | schema_version, analysis_id, analyzer_id, analyzer_version, repository_facts, policy_digest, deadline, attempt | analyzer sees only facts and policy; no FastAPI/DB/provider response object. |
| CategoryResult | schema_version, analysis_id, analyzer_id, category, analyzer_version, status, score, metrics, findings, evidence, coverage, confidence, limitations, duration_ms | score is absent for skipped/error; coverage/confidence are bounded; findings are stable and redacted. |
| Finding | finding_id, analyzer_id, subject, dimension, severity, confidence, reason, evidence | identity is deterministic; location is repository-relative; raw provider text is bounded/redacted. |
| Evidence | evidence_id, source, source_version, repository, path/json_pointer, collected_at, confidence, redaction, content_hash | no secret, token, comment body or raw source; path is relative and pointer is bounded. |
| Coverage | measured, denominator, numerator, scope, reason, evidence_ids | missing denominator is explicit; zero is not used as unavailable. |
| Confidence | value, method, factors, evidence_ids | [0,1], deterministic and explainable; does not silently equal score. |
| AnalysisStatus | state, phase, analysis_id, updated_at, completed_analyzers, failed_analyzers, limitations | overall status distinguishes queued/running/completed/partial/failed/cancelled; analyzer failure is visible but isolated. |
| ScoreInput | schema_version, analysis_id, category_results, score_policy_version, weights_digest | exactly one selected CategoryResult per category; all six categories are represented, including unavailable. |
| RepoHealthResult | schema_version, analysis_id, repository, score_version, overall, score_before_cap, category_scores, statuses, coverage, confidence, evidence_coverage, K, caps, limitations | v1 fields and formula metadata are persisted; result is replayable from ScoreInput and facts digest. |

### Category result status rules

PASS means measured and no policy failure. WARN means measured but partial,
provisional or degraded. FAIL means policy failure, including a confirmed
critical security condition when v1 maps it to failure. SKIPPED means a
capability was deliberately not available. INCONCLUSIVE means the denominator
or evidence quality is insufficient. ERROR means execution/adapter failure.

The orchestrator returns a completed or partial analysis when one analyzer is
ERROR, SKIPPED or INCONCLUSIVE. It returns failed only for request, collector,
score or durable-persistence failures that make the envelope unusable.

## 4. Analyzer isolation map

The six production analyzers are logical bounded contexts. They may share the
same worker process, but they have separate input/output contracts, policies,
adapter modules and test suites.

| Analyzer | Collector/input | Normalized facts | Business logic/policy | Evidence | External boundary |
| --- | --- | --- | --- | --- | --- |
| Documentation | repository files and existing documentation facts | DocumentationFacts: files, completeness, instructions, readability, Vale observations | calibration_policy_v2.documentation_score plus Vale policy; preserve calibrated penalties and denominator rules | relative document paths, Vale JSON pointer/hash, policy revision | Vale CLI through ProcessPort; no Vale source copy |
| Activity | local Git and PyDriller | ActivityFacts/PyDrillerFacts with commit windows, authors, churn, recency, empty/duplicate status | calibration_policy_v2.activity_score and existing PyDriller share/overlap policy | commit SHA/window summary, no author secrets | PyDriller library adapter plus Git facts |
| Issues | SourceCraft Issues collection and provider permissions | IssuesFacts with issue/PR lifecycle, response/close/backlog components and component availability | partial-component policy, bot/unknown actor rules, issues-sourcecraft-policy-v1 | bounded counts, windows and provider pointers; no comments/login/raw payload | SourceCraft Issues transport/collector only |
| CI/CD | SourceCraft CI runs | CICDFacts with terminal/decisive runs, failure streak, duration, trends, DORA availability | cicd_component_score and calibrated v2 policies | run counts/windows/status aggregates; no logs/secrets | SourceCraft CI transport/collector only |
| Security | SourceCraft AppSec REST | AppSecFacts with scans, groups and redacted finding facts | severity-aware category score and frozen v1 caps | finding/group IDs or hashes, severity/state, file/line where allowed | SourceCraft AppSec REST only |
| Code Health | SonarQube results, git-sizer, Git history and TODO/FIXME facts | CodeHealthFacts with maintainability, complexity, duplication, hotspots/churn, TODO debt and Git structure | current Code Health policy and legacy RepoWise file-level engine; no new formula during migration | relative paths/lines, metric pointers and bounded findings | SonarQube transport, git-sizer ProcessPort, Git/TODO adapters |

The current paths to migrate are:

- Documentation: vale_adapter.py plus the existing documentation/completeness
  source; do not treat repohealth.baseline as a peer score after migration.
- Activity: activity_analyzer.py and pydriller_adapter.py.
- Issues: issues_analyzer.py, issues_facts.py and the SourceCraft-shaped bridge
  in chaoss_adapter.py.
- CI/CD: cicd_analyzer.py, cicd_facts.py and cicd_adapter.py.
- Security: appsec_adapter.py and appsec_analyzer.py.
- Code Health: code_health_collector.py, code_health_facts.py,
  code_health_analyzer.py, sonarqube_adapter.py, git_sizer_adapter.py and
  todo_debt_adapter.py, with health/engine.py retained as the business engine
  until parity is proven.

## 5. Execution model

### Task envelope

Each analyzer task carries:

analysis_id, task_id, idempotency_key, repository ref, analyzer ID/version,
facts digest, policy digest, attempt number, deadline, requested resource
limits and correlation/trace IDs.

The task payload is immutable. A retry creates a new attempt for the same task
identity and must not create duplicate result rows.

### Local executor

The LocalExecutor validates AnalyzerInput, invokes the analyzer object,
enforces the deadline and returns CategoryResult. It is the default for unit,
contract and local integration tests.

### Worker executor

The WorkerExecutor serializes AnalyzerInput, claims a task from QueuePort,
executes the same analyzer entry point in a separate process, validates the
serialized CategoryResult and acknowledges only after durable result write.
The queue implementation is replaceable. The first implementation may use the
existing job table only with explicit task-level claim, lease, acknowledgement,
retry and dead-letter state; phase checkpoint rows alone are not queue state.
A later implementation may use a managed queue. Queue migrations must preserve
task uniqueness and crash-before-ack recovery.

### Timeout, retry, idempotency and cache

- Hard process timeouts kill child trees and produce ERROR/timeout evidence.
- Retry only transient provider/process failures; do not retry validation,
  policy or unsupported-capability results.
- Use bounded exponential backoff with jitter and a per-analyzer retry budget.
- Cache key includes repository ID, head SHA, facts digest, analyzer version,
  policy digest and requested scope. Stale cache hits are visible and never
  silently promoted to fresh.
- Idempotency is enforced at task and analysis envelope persistence.
- Concurrency is bounded separately for repositories, analyzers, external HTTP
  requests and native processes.
- A single analyzer result is failure-isolated. The score engine consumes all
  six category slots and records unavailable/failed slots.

### Observability and security

Every event contains analysis_id, task_id, repository_id, analyzer_id,
analyzer_version, phase, attempt, status, duration_ms, cache_hit, timeout and
failure_kind. Logs never contain tokens, raw payloads, source code, comments,
actor logins or full provider responses.

Metrics: task latency, queue age, analyzer success/error/skipped rates,
coverage/confidence distributions, cache hit rate, provider request rate,
timeouts, retries, output truncation and persistence conflicts.

Tracing: one analysis span with child collection, analyzer, score and
persistence spans; propagate W3C trace/correlation IDs through local and worker
executors.

Resource limits: max files/bytes/commits, output caps, request pages, provider
concurrency, wall-clock deadline, memory/process limits where the platform
supports them. Large repositories must degrade to explicit partial coverage,
not fabricate zero scores.

## 6. Score engine and persistence decision

Repo Health Score v1 in score_engine_v1.py is the only target repo-level score:

- weights: Documentation .15, Activity .15, Issues .15, CI/CD .15, Security
  .20 and Code Health .20;
- K is the weighted coverage × confidence quality;
- minimum score categories is 5 and minimum provisional categories is 4;
- score K thresholds are .75 and .50;
- security caps are 60 for confirmed high and 40 for confirmed critical or
  confirmed secret;
- missing data is excluded from the numeric denominator and remains explicit.

calibration_policy_v2.py remains the single source for Documentation, Activity
and CI/CD calibration functions. No formula copy is allowed in analyzer
packages or config.

The legacy composite.py score is a migration compatibility path only. Before
deletion:

1. identify every caller and public response field;
2. run golden replay for all existing fixtures;
3. run dual composition and record semantic deltas;
4. migrate callers to ScoreInput/RepoHealthResult;
5. preserve a read-only legacy decoder if persisted rows require it;
6. delete only after no runtime, fixture, migration or API consumer remains.

Persistence stores:

- immutable AnalysisEnvelope with request, facts digest, category results and
  RepoHealthResult;
- normalized evidence/findings with redaction and provenance;
- projections for existing UI/API consumers;
- score policy and analyzer version digests for replay;
- idempotency and lifecycle records.

The migration must publish a concrete row mapping: RepositoryHealthSnapshot
owns the immutable analysis identity/status, HealthScoreProjection owns the
public v1 score projection, HealthSourceRun owns source/tool provenance,
HealthRawFact and HealthNormalizedFact own the raw/normalized fact boundary,
and HealthMetricValue owns normalized metric values. Findings/evidence,
coverage, confidence and policy/tool digests must each have an explicit owner.
Alembic changes are additive first; legacy rows remain decodable through
dual-read/backfill and replay/rescore until golden and public-projection parity
passes. No destructive table/column removal is allowed before the deletion
proof.

ORM models remain in infrastructure. Score and analyzer modules receive ports,
not SQLAlchemy sessions or model classes.

## 7. Folder structure

Target logical source layout:

~~~text
packages/core/src/repowise/core/repo_health/
  contracts/
    repository.py
    analysis.py
    facts.py
    analyzer.py
    result.py
    score.py
    versioning.py
  collection/
    ports.py
    sourcecraft/
    git/
    normalization.py
    cache.py
  analyzers/
    documentation/
      collector.py
      adapter.py
      facts.py
      policy.py
      analyzer.py
    activity/
    issues/
    cicd/
    security/
    code_health/
  execution/
    ports.py
    local.py
    worker.py
    queue.py
    retry.py
    cache.py
    observability.py
  orchestration/
    planner.py
    lifecycle.py
    failure_policy.py
  scoring/
    repo_health_v1.py
    calibration_v2.py
  persistence/
    ports.py
    envelope_writer.py
    projections.py
  compatibility/
    legacy_health.py
    legacy_score.py

packages/server/src/repowise/server/
  repo_health_api/
    routes.py
    schemas.py
    dependencies.py

packages/worker/src/repowise/worker/
  main.py
  handlers.py

tests/
  unit/repo_health/
  contract/repo_health/
  adapter/repo_health/
  integration/repo_health/
  golden/repo_health/
  e2e/repo_health/

docs/
  architecture-target.md
  architecture.md
  scoring.md
  analyzers/
  sourcecraft-integration.md
  deployment.md
  development.md
  research/archive/
~~~

The first migration keeps `packages/core` and exposes a `repo_health` namespace.
Phase 6 selected the existing core package's
`repowise-health-worker` entry point as the single deployable worker boundary.
Per-analyzer network services remain optional and trigger-based.

## 8. External dependency and license matrix

The table distinguishes the six canonical production paths from copied tools
that are currently registered or documented. “Can delete local copy” means
after the listed reachability, golden, packaging and legal gates; it is not an
instruction to delete during the planning task.

| Dependency/source | Purpose | Integration mode | Observed license/provenance | Required for target? | Can delete local copy? |
| --- | --- | --- | --- | --- | --- |
| PyDriller pinned commit | Activity Git history facts | Python library adapter | Apache-2.0 in installed metadata | YES | NO; keep dependency, isolate behind Activity collector |
| Vale 3.22 policy/binary | Documentation prose quality | external CLI via ProcessPort | External upstream license not copied locally; verify upstream release notice before redistribution | YES | YES for any vendored binary/source; keep external runtime contract |
| SonarQube Community Build | Code Health maintainability/duplication facts | external server/scanner/Web API | vendor tree has no root LICENSE; build references LGPL URL and includes third-party notices | YES as external service; local source NO | YES after proving no primitive adapter/build/test depends on vendor/sonarqube and preserving required notices |
| git-sizer | Code Health Git structure facts | external CLI via ProcessPort | No local copy/license in this tree; verify selected binary release | YES | YES because it should not be vendored; keep tool discovery contract |
| SourceCraft AppSec | Security facts | hosted REST adapter using injected token | Provider/service boundary; no local source license | YES | YES for local client copy only if replacement keeps REST contract; not a vendored engine |
| SourceCraft CI | CI/CD facts | hosted REST/collector adapter | Provider/service boundary; no local source license | YES | YES for raw client internals only after collector contract tests |
| SourceCraft Issues | Issues/PR facts | hosted REST/collector adapter | Provider/service boundary; no local source license | YES | YES for raw client internals only after collector contract tests |
| CollectOSS | existing activity/issues/metrics source bridge | copied Python tree imported lazily by chaoss_adapter.py | MIT in vendor/collectoss/LICENSE | CONDITIONAL; keep only while the SourceCraft-shaped collector still depends on it | YES after direct normalized collector path and fixture replay pass |
| Perceval | copied Git/GitHub event source | copied Python tree under vendor/chaoss/perceval | GPL-3.0 in local LICENSE | NO for Activity target; possibly legacy provider feature | YES for Repo Health path after callers are removed; retain notice if any other product path uses it |
| GrimoireLab/ELK/SortingHat/SirMordred/Graal | copied CHAOSS orchestration/identity/external analyzers | lazy imports and compatibility adapters | GPL-3.0 observed in CHAOSS copied licenses; individual subtrees must be inventoried | NO for six target analyzers | CONDITIONAL; delete only per subtree after runtime/package reachability audit |
| CHAOSS Metrics | methodology definitions | reference files imported/documented | MIT in vendor/chaoss/metrics/LICENSE | NO runtime requirement | YES from production package; archive references and retain attribution if methodology docs remain |
| RepoCrunch | Forge metadata/async provider adapter | copied Python source | MIT in vendor/repocrunch/LICENSE | NO for six analyzer business logic; may support broader RepoWise product | CONDITIONAL on non-health callers |
| OpenSSF Scorecard | optional local security/quality tool | Go subprocess adapter | Apache-2.0 in vendor/scorecard/LICENSE | NO; Security target is SourceCraft AppSec REST only | YES after native adapter/config/docs/golden reachability is zero |
| RepoHealth | alternative baseline tool | Go subprocess adapter | MIT in vendor/repohealth/LICENSE | NO; not one of six target engines | YES after baseline compatibility readers are gone |
| Criticality Score | priority context | Go subprocess adapter | Apache-2.0 in vendor/criticality_score/LICENSE | NO for Repo Health score; may remain separate priority context temporarily | YES from health production path after consumers are separated |
| Qlty | optional SARIF quality tool | Rust subprocess adapter | Business Source License 1.1 in vendor/qlty/LICENSE.md | NO for target Code Health | YES after adapter/config/fixture reachability zero; legal review required because BSL terms differ |
| Sokrates | optional code metrics | Java subprocess/export adapter | MIT in vendor/sokrates/LICENSE | NO for target Code Health | YES after adapter/config/fixture reachability zero |
| Documentor | documentation-review spike | copied Go source | Apache-2.0 and NOTICE in vendor/documentor | NO | YES after spike/report/reference audit; preserve NOTICE if any redistributed artifact remains |
| Lychee | link-checker spike | copied Rust source | MIT/Apache-2.0 local dual licenses | NO | YES after docs/scripts reachability zero |
| Doc Detective | documentation/API research or spike reference | scoped repository/config/vendor search and reference audit | upstream license only if a local source/binary is found; otherwise record not found after scoped search | NO | YES for local copy/artifact after search and notice review |
| Schemathesis | API testing research or spike reference | scoped repository/config/vendor search and reference audit | upstream license only if a local source/binary is found; otherwise record not found after scoped search | NO | YES for local copy/artifact after search and notice review |
| Hercules | activity/history research or spike reference | scoped repository/config/vendor search and reference audit | upstream license only if a local source/binary is found; otherwise record not found after scoped search | NO | YES for local copy/artifact after search and notice review |
| OpenDigger | repository metrics research or spike reference | scoped repository/config/vendor search and reference audit | upstream license only if a local source/binary is found; otherwise record not found after scoped search | NO | YES for local copy/artifact after search and notice review |
| CHAOSS | methodology or copied metrics source reference | scoped repository/config/vendor search, vendor subtree audit and reference audit | each discovered subtree requires its own source/license/notice row; absent runtime use is recorded explicitly | NO for six target analyzers | CONDITIONAL; delete only per subtree after reachability and legal proof |
| DevLake | repository analytics research or spike reference | scoped repository/config/vendor search and reference audit | upstream license only if a local source/binary is found; otherwise record not found after scoped search | NO | YES for local copy/artifact after search and notice review |

The legal gate is materialized in
`docs/research/archive/repo-health-external-dependencies.json`. It inventories
all copied source trees, external engines and named spikes. It must not delete
a LICENSE, NOTICE, COPYING or generated third-party attribution file merely
because the corresponding executable is removed.

## 9. Spikes, generated artifacts and documentation

### Classification

| Area | Current state | Target action |
| --- | --- | --- |
| production source | packages/core, packages/server, packages/cli and required config | keep; move only behind contract-preserving boundaries |
| tests and fixtures | tests/unit/health, tests/integration, tests/fixtures/health and analyzer fixtures | keep; split by contract/adapter/integration/golden level |
| research evidence | docs/category-score-calibration.md, docs/final-score-validation.md, calibration reports and controlled fixtures | keep as docs/research/archive until score methodology defense is no longer needed |
| generated live runs | spikes/*/runs, JSON/CSV/log exports, $out and tool output folders | do not package; archive selected redacted evidence, delete local generated output only after worktree ownership is confirmed |
| Graphify output | packages/core/src/graphify-out | audit-only; already ignored by .gitignore; never import/package |
| temporary source snapshots | .sources and generated bin outputs | keep ignored; no production imports |

Phase 7 keeps all copied vendor trees and research upstream snapshots whose
runtime or legal reachability is not yet proven zero. The cleanup verifier
reports the missing `.sources` provenance roots as a visible warning; this is a
blocked provenance gate, not a deletion authorization. Generated runs and
upstream research snapshots are ignored by Git and excluded from the worker
wheel, while their small README/provenance files remain available for audit.

Minimal public docs after migration:

README.md

docs/architecture.md
docs/architecture-target.md
docs/scoring.md
docs/analyzers/README.md
docs/analyzers/documentation.md
docs/analyzers/activity.md
docs/analyzers/issues.md
docs/analyzers/cicd.md
docs/analyzers/security.md
docs/analyzers/code-health.md
docs/sourcecraft-integration.md
docs/deployment.md
docs/development.md
docs/research/archive/

Existing reference pages can be redirected or merged only after links and
verification commands are updated. Do not delete calibration evidence before
the parity and release process has a replacement provenance record.

## 10. Migration phases

1. Baseline and reachability ledger: freeze behavior, collect dependency graph,
   inventory contracts, score paths, callers, configs, scripts, fixtures,
   licenses and artifacts.
2. Contract kernel: add versioned JSON/Pydantic contracts and adapters around
   current AnalyzerContext/AnalyzerResult without behavior changes.
3. Facts boundary: create RepositoryFacts and provider/local collectors;
   remove raw provider payloads from analyzer inputs.
4. Analyzer isolation: create six packages and migrate one analyzer at a time;
   keep old facades and run parity.
5. Score and persistence boundary: make ScoreInput/RepoHealthResult canonical;
   migrate storage/API projections; retain legacy decoder/fallback only when
   evidence requires it.
6. Execution boundary: add task envelope, local executor, worker executor,
   queue port, retries, timeouts, idempotency and observability.
7. Cleanup: remove unreferenced analyzer registrations, legacy adapters,
   competing score path, stale configs/scripts and external copies only after
   deletion gates.
8. Documentation and artifacts: consolidate docs, archive research, enforce
   generated-output policy and legal notices.
9. Full verification and rollout: dual-run, replay, contract tests, API
   compatibility, rollback rehearsal and final deletion proof.

Each phase must leave the repository runnable. No big-bang rewrite and no
formula change is allowed.

## 11. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A legacy caller depends on composite.py | caller ledger, dual-run and legacy decoder before deletion |
| Analyzer output changes during movement | golden CategoryResult replay and contract tests before/after each move |
| Missing data becomes zero | explicit Coverage/Confidence/AnalysisStatus validators and no-zero tests |
| SourceCraft payload leaks into analyzer | typed RepositoryFacts and import-boundary checks |
| One provider outage blocks all categories | collector capability states plus analyzer-level failure isolation |
| Worker retry duplicates rows | deterministic task ID, idempotency key and unique persistence constraints |
| Large repositories exhaust memory/time | bounded collection, subprocess caps, deadlines and partial coverage |
| Secrets enter logs/evidence/cache | redaction policy, allow-listed fields and negative tests |
| Vendor removal breaks a broader RepoWise feature | whole-repository reachability, package build and integration verification |
| Legal notice is removed incorrectly | license manifest before deletion and notice-preservation gate |
| Worktree contamination | dedicated clean implementation branch after this plan; never reset current dirty worktree |

## 12. Verification plan

Required levels:

- Unit: pure policies, fact normalization, score arithmetic, validators and
  deterministic IDs.
- Contract: every published model JSON round-trip, unknown-field rejection,
  version negotiation and transport-neutral fixtures.
- Adapter: Vale/PyDriller/SourceCraft/SonarQube/git-sizer process/HTTP
  behavior, redaction, timeout and malformed payloads.
- Integration: collector to analyzer, analyzer to score, score to persistence
  projection, cache and worker task lifecycle.
- Golden/parity: calibration-v2 fixtures, Repo Health Score v1 fixtures,
  legacy-vs-target comparison and existing per-file Code Health snapshots.
- End-to-end: API request to persisted analysis to stable public response,
  including partial analyzer failure and resume/retry.

Gate commands to be wired into the implementation plan:

~~~text
uv run pytest -q tests/unit/health
uv run pytest -q tests/integration/test_health_composition.py tests/integration/test_issues_analyzer.py tests/integration/test_vale_documentation.py
uv run pytest -q tests/unit/health/test_repo_health_score_v1.py tests/unit/health/test_calibration_v2_policy.py tests/unit/health/test_analyzer_integration_parity.py
uv run python scripts/verify_repo_health_score_v1.py
uv run python scripts/verify_health_stack.py
uv run python scripts/vendor_sources.py --verify
uv run python scripts/verify_source_update.py
uv run python scripts/verify_health_docs.py
uv run python scripts/verify_health_completion.py
uv run python scripts/verify_vale_fixture.py
uv run python scripts/verify_pydriller_activity_fixture.py
uv run python scripts/verify_issues_fixture.py
uv run python scripts/verify_cicd_fixture.py
uv run python scripts/verify_code_health_fixture.py
~~~

Acceptance is not “the new folders exist”. Acceptance is:

- all six analyzers run from local and worker executors through serialized
  contracts;
- one analyzer failure produces a visible partial result and does not abort
  unrelated categories;
- score v1 values, K, caps, coverage/confidence and calibration-v2 outputs
  are unchanged on golden fixtures;
- API compatibility is preserved through projections;
- no analyzer imports FastAPI, UI, DB or another analyzer;
- no production module imports raw SourceCraft payload types;
- deletion candidates have zero runtime/package/test reachability and a
  recorded legal/notice decision;
- the repository remains runnable after every phase.

## 13. CLEANUP decision table

| Path | Current purpose | Decision | Reason | Risk | Verification |
| --- | --- | --- | --- | --- | --- |
| packages/core/src/repowise/core/analysis/health/integrations/__init__.py | import-time registration of 19 adapters | move/split | bootstrap mixes six target analyzers with legacy/auxiliary tools | hidden import side effects | explicit six-analyzer registry test; import smoke test |
| packages/core/src/repowise/core/analysis/health/integrations/contracts.py | compatibility export of neutral contracts | keep temporarily, then move | existing callers need a safe bridge | premature removal breaks fixtures/callers | import graph and contract parity |
| packages/core/src/repowise/core/analysis/analyzer_integration/contracts.py | current generic AnalyzerContext/AnalyzerResult contracts | keep and evolve behind versioned contracts | existing kernel is valuable foundation | schema drift | JSON golden and old facade tests |
| packages/core/src/repowise/core/analysis/health/integrations/chaoss_adapter.py | CollectOSS/CHAOSS/Graal bridge for activity/issues/extra metrics | split; delete only unused branches | file owns multiple bounded contexts and lazy vendor imports | SourceCraft fixture regression | per-source reachability and analyzer parity |
| packages/core/src/repowise/core/analysis/health/integrations/native_adapters.py | Scorecard/RepoHealth/Criticality/Qlty/Sokrates parsers and runners | move to auxiliary compatibility; candidate delete | not part of six canonical target paths | hidden ranking/CLI consumer | full repo search, API regression, native golden |
| packages/core/src/repowise/core/analysis/health/score_engine_v1.py | frozen six-category score | keep as canonical score engine | source of truth for v1 | accidental formula cleanup | v1 golden, config digest and monotonicity tests |
| packages/core/src/repowise/core/analysis/health/composite.py | legacy eight-dimension score | keep behind compatibility, later delete if proven | still reachable through default fallback and tests | persisted legacy snapshots/API changes | caller ledger, dual-run and replay |
| packages/core/src/repowise/core/persistence/crud/analysis/health_envelope.py | calculates and persists health envelopes | split into score port and persistence adapter | persistence currently knows scoring implementation | replay/projection drift | persistence integration and stored digest checks |
| packages/server/src/repowise/server/routers/code_health/canonical.py | canonical health read model | keep, refactor behind read port | public API behavior must remain stable | response shape regression | API contract/e2e snapshots |
| packages/server/src/repowise/server/mcp_server/tool_health.py | direct ORM health queries and serialization | move to read service | MCP bypasses API/persistence boundary | MCP payload regression | MCP golden/response-size tests |
| config/analyzers/repo-health-score-v1.yaml | frozen v1 score policy | keep, make contract-owned | explicit weights/K/caps are source of truth | config/code divergence | config digest and golden score |
| config/analyzers/health-score.yaml | legacy eight-dimension policy | keep only while legacy callers exist, then archive/delete | competing policy path | old persisted result replay | caller and replay audit |
| config/analyzers/{native-tools,metrics,forge}.yaml | optional/copied engine/source policies | classify per reachability; move out of six analyzer config | current production config advertises 19 analyzers | broader RepoWise feature regression | config loading tests and clean bootstrap |
| vendor/scorecard, vendor/repohealth, vendor/criticality_score | copied Go engines | candidate delete from health production package | not in target six analyzers | priority/security auxiliary consumers | zero reachability + native golden |
| vendor/qlty, vendor/sokrates | optional code-quality engines | candidate delete | target Code Health is SonarQube/git-sizer/Git/TODO | alternative quality signal loss | code-health parity and config audit |
| vendor/sonarqube | copied SonarQube primitives/source | candidate delete after adapter audit | target uses external SonarQube service; local tree is large | hidden primitive parser dependency | adapter/build/test/package audit; legal notice inventory |
| vendor/collectoss and vendor/chaoss/* | copied data collection/orchestration trees | conditional move/delete | only needed for legacy source bridges or wider RepoWise features | activity/issues behavior and GPL obligations | direct collector replay, package import audit |
| vendor/repocrunch | Forge client source | conditional keep outside Repo Health | may support repository metadata outside six analyzers | API/CLI forge regression | whole-repo runtime search |
| vendor/documentor, vendor/lychee | copied documentation/link spikes | candidate delete | no target production analyzer dependency | undocumented script/reference | docs/script search and notice audit |
| spikes/{activity,cicd,code_health,documentation,issues,scoring} | live runs, calibration and research material | archive selected evidence; delete generated runs | research evidence is useful but not production package | loss of methodology defense | redacted archive manifest and reproducibility links |
| $out/sonarqube-* and other live JSON/CSV/log outputs | generated external-tool state | delete or keep local-only, never package | generated artifacts pollute worktree/package | deleting user-owned run output | verify ownership and .gitignore/package manifest |
| docs/CHANGELOG.md and historical reports | broad historical documentation | keep/archive, do not make runtime docs | history may explain behavior and parity | broken links | docs link checker and archive index |
| Doc Detective/Schemathesis/Hercules/OpenDigger/DevLake references | methodology/spike references | archive/delete only after exact search | no verified target production path | losing research provenance | source/reference inventory and clean search |

### Safe deletion proof

For every DELETE row, the implementer must attach all of:

1. repository-wide static references = zero, excluding archive attribution;
2. runtime registry and entry-point reachability = zero;
3. packaging/manifests/config/script references = zero;
4. tests and fixtures either removed as obsolete with explanation or migrated;
5. golden/parity and API/e2e verification pass;
6. license/NOTICE/COPYING inventory recorded and preserved where required;
7. one reversible commit before physical removal.

Until all seven checks are true, the item is MOVE, ARCHIVE or KEEP—not DELETE.
