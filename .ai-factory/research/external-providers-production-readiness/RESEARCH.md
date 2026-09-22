# Research Report

## 1. Repository and baseline

The product is a single Python backend package under `src/repo_health`. The
runtime contract is:

```text
AnalysisRequest
  -> CollectionService
  -> RepositoryFacts
  -> six analyzer factories
  -> ScoreEngineV1
  -> persistence/API or worker
```

The current worktree is on `codex/manual-repository-validation-lab` and has
intentional uncommitted changes from the previous validation task. No reset,
stash, checkout, or destructive cleanup is allowed. The existing suite was
run before this checkpoint:

```text
uv run pytest -q
119 passed, 1 warning
```

The warning is the existing Starlette/httpx deprecation warning and is not a
product failure.

## 2. Current composition evidence

`src/repo_health/runtime.py` currently constructs these collectors:

- `GitCollector`
- `PyDrillerCollector`
- `ValeCollector`
- `TodoHistoryCollector`
- `GitSizerCollector`
- `SonarQubeCollector` when Sonar URL and token are configured, otherwise an
  explicit unavailable collector
- unavailable placeholders for `issues.provider` and `cicd.provider`
- `SourceCraftAppSecCollector` when SourceCraft URL and token are configured,
  otherwise an explicit unavailable collector

The common `SourceCraftClient` already provides bearer authentication,
timeout, retry, status mapping, and secret-safe logging. However,
`SourceCraftIssuesCollector` and `SourceCraftCicdCollector` are currently
generic legacy resource wrappers with `/api/issues` and `/api/cicd` defaults,
and the composition root does not instantiate them. This is the production
gap, not a scoring or analyzer gap.

The normalized analyzers already accept the required contract-level
observations:

- Issues: sample/count, lifecycle, response/comment availability, backlog and
  trend observations, coverage/confidence.
- CI/CD: decisive run count, failure rate/streak, duration percentiles,
  deltas, coverage/confidence.

Therefore provider work should normalize official payloads into these existing
keys and leave analyzer formulas untouched.

## 3. Official SourceCraft API evidence

The official interactive REST reference and Swagger document were checked on
2026-09-22:

- [Official SourceCraft API reference](https://api.sourcecraft.tech/docs/index.html)
- [Official SourceCraft OpenAPI/Swagger document](https://api.sourcecraft.tech/sourcecraft.swagger.json)
- [Official REST API overview and PAT authentication](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/operations/api-start)
- [Official `src api` transport and pagination behavior](https://vibe.sourcecraft.dev/portal/docs/en/cli-ref/src-api)
- [Official CI/CD workflow reference](https://vibe.sourcecraft.dev/portal/docs/en/sourcecraft/ci-cd-ref/workflows)

The current official schemas establish:

1. `GET /repos/{org_slug}/{repo_slug}/issues` returns a
   `ListRepositoryIssuesResponse` envelope with `issues` and optional
   `next_page_token`; query parameters include `page_size`, `page_token`,
   `sort_by`, and `filter`.
2. `GET /repos/{org_slug}/{repo_slug}/cicd/runs` returns a `ListRunsResponse`
   envelope with `runs` and optional `next_page_token`; query parameters are
   `page_size` and `page_token`.
3. CI run records expose `dates`, `status`, `workflows`, and error fields;
   current status values include `success`, `failed`, `canceled`, `timeout`,
   `skipped`, and non-terminal states.
4. The API overview specifies PAT bearer authentication. The application must
   keep the token at the transport boundary and must never place it in facts,
   persistence, logs, or reports.
5. The old non-`/repos` CI endpoints are explicitly marked deprecated in the
   official Swagger document. They are not acceptable production defaults.

## 4. Live SourceCraft evidence

The installed `src` CLI is authenticated without exposing its credential in
output. `src auth status --json=authenticated,user,environment` reported:

```json
{"authenticated":true,"environment":"ExtProd"}
```

`src envs` reported the official `https://api.sourcecraft.tech` endpoint.
The controlled organization has dedicated fixtures, including:

- `artem03102006/repo-health-calibration-issues` (private, 8 issues)
- `artem03102006/repo-health-calibration-ci-healthy`
- `artem03102006/repo-health-calibration-ci-bad`
- `artem03102006/repo-health-calibration-ci-mixed`
- `artem03102006/repo-health-calibration-security`

Safe shape-only live probes against the Issues fixture returned:

```text
GET repos/{owner}/{repo}/issues?page_size=2
  status: 200
  keys: issues, next_page_token
  issue rows: 2
  next page: present

GET repos/{owner}/{repo}/cicd/runs?page_size=2
  status: 200
  keys: runs, next_page_token
  run rows: 0
  next page: absent
```

Response bodies were not copied into the repository or research artifacts.
Token values were not printed or persisted.

## 5. Docker and SonarQube environment evidence

Docker Desktop was started without changing or deleting images, containers, or
volumes. The client is installed, but the daemon remains unavailable:

- `docker context ls` selects `desktop-linux`.
- `docker info` fails because `dockerDesktopLinuxEngine` is absent.
- `docker desktop status` reports `stopped`.
- Docker Desktop's supplied error identifies `com.docker.build` exit status 1.
- Docker VM logs show `dockerd failed to start: starting rpcbind: signal:
  killed` and, on the retry, `starting rpcbind: context canceled`.
- The host has critically low free space on the relevant volume (the native
  Sonar logs report approximately 6.07% free), which is an environmental risk.

This is an external environment limitation. No Docker data reset or broad
cleanup is safe to perform automatically. The repository can nevertheless use
the already-running native SonarQube instance for the required live REST
verification, provided its official scanner is used and the result is clearly
labelled as native rather than containerized.

Native SonarQube evidence:

- Java process runs the extracted SonarQube 26.9.0.129388 distribution under
  `D:\RepoHealthCalibration`.
- `GET http://127.0.0.1:9000/api/system/status` returns HTTP 200 and `status=UP`.
- `GET http://127.0.0.1:9000/api/authentication/validate` is reachable.
- The official SonarScanner CLI 8.1.0.6389 archive is already present under
  the external validation-tool directory and is not part of the production
  package.
- `vale`, `git-sizer`, and `sonar-scanner` are not on PATH; pinned validation
  copies are available outside the repository. Production capability detection
  must continue to report them unavailable when their paths are not configured.

## 6. Capability and configuration findings

`RuntimeConfig` currently tracks `SOURCECRAFT_TOKEN` presence only. The local
SourceCraft CLI session is configured through `SOURCECRAFT_PAT`; the runtime
must support this existing safe environment convention without copying the
secret into typed configuration. The smallest compatible design is a
credential provider that resolves the explicitly selected variable, with a
fallback to `SOURCECRAFT_PAT` only when `SOURCECRAFT_TOKEN` is absent. The
capability report should mark SourceCraft available when URL plus either
supported credential is present, while public readiness output remains boolean
only.

The existing Sonar capability correctly requires URL plus token and the
collector requests `/api/measures/component` using `repository.repository_id`
as the project key. A live scanner must therefore publish a project using a
sanitized key matching that repository identity before the collector is called.

## 7. Safety constraints for implementation

- Preserve `ScoreEngineV1`, calibration-v2 modules, weights, caps, thresholds,
  analyzer IDs, and golden fixtures.
- Do not make GitHub Issues/Actions/AppSec substitutes for SourceCraft.
- Do not use deprecated SourceCraft CI endpoints.
- Keep AppSec as its own adapter and preserve the scans → defect-groups →
  findings chain.
- Do not add a SourceCraft SDK dependency; the existing `httpx` transport
  boundary is sufficient and keeps the provider independently testable.
- Normalize bounded counts and timing/status fields only; do not persist raw
  provider payloads or issue text, comments, workflow logs, URLs with secrets,
  or token-like values.
- Use one production composition root for API and worker. Tests may provide
  explicit fake collectors or transports.
- Live provider tests must use the controlled SourceCraft fixtures and a local
  SonarQube endpoint only.

## 8. Open questions to resolve in the plan

1. Which exact official issue fields and comment endpoint can provide the
   existing response/resolution metrics without issuing unbounded per-issue
   requests? The safe first production version may expose count/lifecycle
   facts and mark comment-derived metrics partial when comments are not
   collected.
2. How should empty CI history map to existing analyzer semantics? It must
   remain unavailable/inconclusive, never numeric zero.
3. Whether the controlled CI fixture contains completed runs in the current
   account; if not, the live provider can still be verified at envelope and
   empty-history level, while a completed-run numeric path remains an explicit
   external fixture limitation.
4. Whether the native SonarQube instance has a usable validation credential or
   anonymous analysis enabled. If not, create a short-lived local token only
   through the local Sonar UI/API and keep it process-local.

## 9. Recommended bounded change set

The plan should contain these implementation slices:

1. Add official-path, page-token aware SourceCraft transport helpers and
   separate Issues and CI/CD normalizers.
2. Add sourcecraft PAT compatibility and canonical capability detection without
   storing the token.
3. Wire Issues and CI/CD in `_build_collectors` only when SourceCraft is
   available; otherwise retain explicit unavailable collectors.
4. Add unit/contract tests for normal, pagination, empty, malformed, timeout,
   auth, 404, rate-limit, and partial behavior, plus composition-root parity.
5. Run the official SonarScanner against a small controlled checkout and then
   verify the existing Sonar collector returns real measures and Code Health
   facts.
6. Run the controlled SourceCraft pipeline and one full six-category E2E;
   document Docker failure/native Sonar evidence in
   `docs/validation/external-providers-readiness.md`.
