# SourceCraft integration

Set `SOURCECRAFT_URL` and inject `SOURCECRAFT_TOKEN` (or the existing
`SOURCECRAFT_PAT`) through the runtime environment or a secret manager.
`SourceCraftClient` resolves credentials only when a request is executed. Tokens are never included in `RepositoryFacts`,
`AnalyzerTask`, SQLite rows, logs or REST responses. The public SourceCraft API
uses bearer PAT authentication at the transport boundary.

The adapter classifies authentication, permission, unavailable and malformed
responses separately. Collection returns explicit source status and limitation
metadata so the six-category pipeline can complete partially.

The production composition automatically wires SourceCraft Issues and CI/CD
resource collectors plus the separate AppSec chain. Issues and CI/CD use the
official repository-scoped REST routes with bounded `next_page_token`
pagination:

```text
GET /repos/{org_slug}/{repo_slug}/issues
GET /repos/{org_slug}/{repo_slug}/issues/{issue_slug}/comments
GET /repos/{org_slug}/{repo_slug}/cicd/runs
```

```text
GET /v1/scans
  → GET /v1/defect-groups?scan_id=...
  → GET /v1/findings?scan_id=...&defect_group_id=...
```

Only bounded counts, timestamps-derived measures, durations and source status
enter normalized facts. A failed AppSec
group leaves successful groups intact and marks Security partial; missing or
malformed responses never become zero findings. Git checkout, Vale, PyDriller,
SonarQube, git-sizer and TODO-history are separate normalized collectors built
by the same production composition root. Readiness reports capability/config
state only; it never performs a full analysis or returns a secret.

## Assessment profiles

`PUBLIC` is the safe default and excludes owner-authorized SourceCraft Issues,
CI/CD and AppSec collection before the network call. Their CategoryResult is
skipped/unavailable with an explicit `assessment.public_sourcecraft_excluded`
limitation. `OWNER_EXTENDED` is available only to a trusted request context
with a Yandex ID subject and authorized SourceCraft access. A client cannot
enable it by submitting a profile string alone.

AppSec lifecycle is preserved in normalized `SecurityFacts` as one of
`NO_SCAN`, `FINISHED_ZERO_FINDINGS`, `FINISHED_WITH_FINDINGS`, `FAILED`,
`UNAVAILABLE` or `PARTIAL`. Only a completed scan can produce a numeric
security result. No scan, failed scan and unavailable provider remain
inconclusive/skipped with zero coverage; partial group collection carries
partial coverage and a limitation. `FINISHED_ZERO_FINDINGS` is distinct from
`NO_SCAN` and may legitimately produce a complete 100 security score.
