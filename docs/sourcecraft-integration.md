# SourceCraft integration

SourceCraft is a collector/provider boundary, not an analyzer dependency.
REST responses are authenticated in the collector, normalized into
`RepositoryFacts`, redacted, bounded and then passed to analyzers as contract
data. Raw payloads, request objects and tokens never enter `AnalyzerInput`,
task JSON, evidence, logs or public projections.

The live paths are:

- Issues: SourceCraft Issues with explicit partial-component availability;
- CI/CD: SourceCraft CI with calibrated-v2 terminal/decisive-run policy;
- Security: SourceCraft AppSec REST only, with severity-aware v1 caps.

Credentials are injected by the deployment secret manager or environment
(`SOURCECRAFT_PAT` for the existing local verification path). Never commit
them or paste live payloads into fixtures. 401/403/404, rate limits, timeout
and provider unavailability become visible limitations or unavailable
category states; they do not become a score of zero.

Collectors apply bounded pagination, concurrency, retries and output limits.
Evidence stores source/version and bounded JSON pointers or hashes, not issue
body text, access tokens or provider response dumps. The adapter contract is
tested independently of FastAPI and SQLAlchemy.

Use fixtures by default. Live checks are explicit and must be redacted:

```text
uv run python scripts/verify_issues_fixture.py
uv run python scripts/verify_cicd_fixture.py
SOURCECRAFT_PAT=... uv run python scripts/verify_cicd_fixture.py --live
```
