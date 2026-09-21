# SonarQube spike

Verdict: **PARTIAL FIT; REAL ANALYSIS BLOCKED BY THE DOCKER DAEMON**.

SonarQube Community Build is a server-backed static-analysis platform. It is a
strong match for code smells, bugs, vulnerabilities, security hotspots,
duplication, coverage, quality gates, and measure history, but the practical
integration is Scanner CLI → SonarQube server → Web API. It is not a
single-process repository linter that can emit final findings from this
workspace alone.

## Source and license

- Upstream: `https://github.com/SonarSource/sonarqube.git`
- Cloned at: `96ccb4dc02d832cd97dd18872bdc9ce3298a826f`
- Source version: `26.10` (`upstream/gradle.properties`)
- License: GNU LGPL v3 (`upstream/LICENSE.txt`, `NOTICE.txt`, and README)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Standard startup/build evidence

The source Gradle wrapper is present and the standard environment probe passed:

```text
upstream/gradlew.bat --version -> Gradle 8.14.3, Java 21.0.11
```

No full Gradle server build was started because the requested practical path is
the official ready-made container and the Docker daemon is unresponsive in this
environment. The wrapper result is in `runs/gradle-version.*`.

The official container attempt was bounded to five seconds:

```text
docker run --rm sonarqube:community sonar-scanner --version -> timeout_after_5s
```

No container, database, project, or analysis was created. See
`runs/docker-sonarqube.*`.

## Fixture applicability

The fixture contains Python, JavaScript, YAML, Markdown, requirements, and
inert secret-shaped text, but no `sonar-project.properties`, scanner-generated
coverage report, or CI analysis history. The inventory is in
`runs/fixture-inventory.txt`. Without a running server and scanner, no issue or
measure count is claimed.

## Output and metric boundary

The source README describes the Community Build as the static-analysis engine.
The generated Web API client and server modules expose structured HTTP results.
Relevant measures include:

- `code_smells`, `bugs`, `vulnerabilities`, and security-hotspot measures;
- `coverage`, `ncloc`, `duplicated_lines_density`, complexity, and technical
  debt;
- reliability/security/maintainability ratings and the quality-gate status.

The Web API client source documents `measures/search_history`, whose request
accepts a project component, metric keys, branch/pull-request selector, and
date range. Equivalent API calls can retrieve the historical series after an
analysis is uploaded. Issues and quality-gate endpoints are exposed in the
same server Web API modules; their JSON is the natural structured adapter
format.

Quality gates are server-side policies evaluated over current/new-code
measures. A scanner run should be treated as successful only after the
background Compute Engine task completes and the quality-gate status is read
back from the server. A scanner process exit alone is not the complete health
signal.

## Integration boundary and runtime

The adapter would:

1. create or select a project key and scanner configuration;
2. invoke the official scanner with a token and source path;
3. poll the compute-task/background-analysis status;
4. call Web API measures/issues/quality-gates endpoints; and
5. normalize JSON findings, measures, history, and gate status.

Server startup is heavyweight compared with a local linter and needs persistent
storage plus a supported database configuration. Analysis cost grows with
source lines, language plugins, enabled rules, coverage/duplication inputs, and
history. The fixture run is therefore blocked by infrastructure, not by a
known SonarQube finding.

The LGPL v3 license and the server/token/database operational boundary should
be recorded before embedding the platform into a product. It remains a good
candidate when a shared SonarQube service already exists; it is a poor fit for
a self-contained per-repository subprocess without that service.
