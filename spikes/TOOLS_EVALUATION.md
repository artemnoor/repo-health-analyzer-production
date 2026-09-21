# Upstream tools evaluation

All tools below were evaluated against the same checked-out SourceCraft audit
fixture where the tool's input model allowed it. “Partial” means the upstream
tool or its methodology is useful, but the full requested production-shaped
run was blocked by the fixture, runtime, or deployment boundary.

| Category | Tool | Exact upstream @ SHA | Version / probe | Ran? | Real fixture? | Useful output? | Structured output? | Integration method | Runtime complexity | License | Limitation | Verdict |
|---|---|---|---|---:|---:|---|---|---|---|---|---|---|
| Documentation | Doc Detective | `doc-detective/doc-detective@dc88004a` | 4.38.4 / Node CLI | Yes | Partial: README negative case and executable sidecar | Executable-doc pass/fail, HTML/run folder | JSON, HTML, run-folder artifacts | Node CLI | Startup plus configured steps; shell/browser steps dominate | AGPL-3.0-only | Ordinary README is not a test spec; source build hit Windows Node PATH/engine issues | PARTIAL |
| Documentation | Vale | `vale-cli/vale@ba6a2c6a` | v3.22.0 / Windows binary | Yes | Yes | Lint diagnostic and prose metrics | JSON | CLI | Linear in selected document bytes plus style matching | MIT | Source build incompatible with current Go toolchain; warnings are non-fatal by default | WORKS |
| Documentation | Schemathesis | `schemathesis/schemathesis@94e23b5e` | 4.27.3 / Python CLI | Yes | No API schema | Schema-loading failure only; no API metrics | Terminal/reports when a schema exists | Python CLI/library | Hypothesis-driven API exploration; request count and schema size dependent | MIT | Fixture has no OpenAPI/GraphQL schema; Windows output encoding also needed UTF-8 | PARTIAL |
| Activity | PyDriller | `ishepard/pydriller@a527c83b` | 2.12 / Python library | Yes | Yes | Commits, authors, files, churn, diffs, process metrics | Custom JSON runner | Python library or subprocess wrapper | Reachable commits plus changed-file/diff volume | Apache-2.0 | Ref scope and deduplication must be chosen explicitly | WORKS |
| Activity | Hercules | `src-d/hercules@68bb211f` | v10.7.2 / Windows binary | Yes, release binary | Yes | Developers, burndown, file history, commit/language stats | YAML | CLI | History, diffs, file-history analyses; memory grows with report size | Apache-2.0 | Exact source build failed with current Go/tree-sitter stack; missing path emits panic-style stderr | PARTIAL |
| Issues | OpenDigger | `X-lab2017/open-digger@63e4b89e` | 1.0.0 / source algorithms | Methodology reproduced | No issue-event data | Response, resolution, age, thresholds, quantiles reproduced synthetically | JSON reproduction; service emits query data | ClickHouse/public JSON service or ported algorithms | External event-store queries over issue history | Apache-2.0 | No fixture issue events or ClickHouse; npm install hit sharp/libvips timeout | PARTIAL |
| Issues | CHAOSS Metrics | `chaoss/metrics@fae1f4df` | Methodology repository | No runtime | No | Metric definitions, templates, and data-ethics guidance | No executable output in exact clone | Specification-to-implementation mapping | No runtime; implementation-dependent | MIT | Exact clone is a methodology repository, not an issue-metric engine | PARTIAL |
| CI/CD | Apache DevLake | `apache/devlake@e744aefe` | Source clone / compose model | Bounded probes | No CI history | Source-backed normalized model, dashboard formulas, webhook boundary | SQL/Grafana/API contracts; no live report | Docker deployment, REST/webhook, SQL/Grafana | Containers, ingestion, database, and dashboard queries | Apache-2.0 | Docker daemon probe timed out; compose config needs `.env`; fixture has config only | PARTIAL |
| Code health | SonarQube | `SonarSource/sonarqube@96ccb4dc` | 26.10 / source and container probe | Bounded probes | No analysis | Source/API measure and quality-gate contract | Web API JSON when server runs; no live output | Scanner → server/compute task → Web API | Scanner plus server/database analysis; history queries add storage cost | LGPL-3.0 | Docker probe timed out; fixture lacks scanner config, coverage, and server history | PARTIAL |
| Code health | git-sizer | `github/git-sizer@88eaa80d` | Source build / Go CLI | Yes | Yes | Git object, history, tree, blob, and checkout-size metrics | JSON v2 | CLI | Reachable Git object graph; time/memory scale with refs and history | MIT | Requires a valid local Git repository and measures reachable refs only | WORKS |

The strongest immediate candidates for a repository-local analyzer are Vale,
PyDriller, and git-sizer. Doc Detective is useful when executable
documentation is explicitly authored, while the remaining tools require an
external schema, issue-event store, CI/CD service, or code-analysis server.
