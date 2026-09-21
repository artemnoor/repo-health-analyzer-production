# SourceCraft integration

Set `SOURCECRAFT_URL` and inject `SOURCECRAFT_TOKEN` through the runtime
environment or a secret manager. `SourceCraftClient` resolves credentials only
when a request is executed. Tokens are never included in `RepositoryFacts`,
`AnalyzerTask`, SQLite rows, logs or REST responses. The public SourceCraft API
uses bearer PAT authentication at the transport boundary.

The adapter classifies authentication, permission, unavailable and malformed
responses separately. Collection returns explicit source status and limitation
metadata so the six-category pipeline can complete partially.

The production composition automatically wires SourceCraft Issues and CI/CD
resource collectors plus the AppSec chain:

```text
GET /v1/scans
  → GET /v1/defect-groups?scan_id=...
  → GET /v1/findings?scan_id=...&defect_group_id=...
```

Only bounded counts and source status enter normalized facts. A failed AppSec
group leaves successful groups intact and marks Security partial; missing or
malformed responses never become zero findings. Git checkout, Vale, PyDriller,
SonarQube, git-sizer and TODO-history are separate normalized collectors built
by the same production composition root. Readiness reports capability/config
state only; it never performs a full analysis or returns a secret.
