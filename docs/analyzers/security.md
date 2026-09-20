# Security analyzer

- ID: `repo-health.security`
- Input: normalized SourceCraft AppSec REST facts.
- Output: `CategoryResult` with redacted findings, evidence, coverage,
  confidence, limitations and severity-aware score signals.
- Policy: `security-v1` / `sourcecraft-appsec-policy-v1` in
  `config/analyzers/appsec.yaml`.
- External engine: SourceCraft AppSec REST only.

Confirmed high, critical and secret findings preserve the frozen Repo Health
Score v1 caps. Tokens, comments, raw payloads and provider secrets are never
stored in evidence or logs.

Checks: AppSec adapter/analyzer tests and the frozen score/parity suite.
