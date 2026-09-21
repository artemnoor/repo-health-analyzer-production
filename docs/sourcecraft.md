# SourceCraft integration

Set `SOURCECRAFT_URL` and inject `SOURCECRAFT_TOKEN` through the runtime
environment or a secret manager. `SourceCraftClient` resolves credentials only
when a request is executed. Tokens are never included in `RepositoryFacts`,
`AnalyzerTask`, SQLite rows, logs or REST responses.

The adapter classifies authentication, permission, unavailable and malformed
responses separately. Collection returns explicit source status and limitation
metadata so the six-category pipeline can complete partially.

SourceCraft resources currently used by the pipeline are repository metadata,
issues, CI/CD runs and AppSec findings. Git checkout and local tools are
separate collectors. Readiness reports configuration presence only; it never
performs a full analysis or returns a secret.
