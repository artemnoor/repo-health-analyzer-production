# Deployment

## Minimal production shape

Run one API process and one Repo Health worker. The worker is the existing
package entry point, not a second analyzer implementation:

```text
uv run repowise-health-worker --check
uv run repowise-health-worker --validate-task task.json
```

For local smoke checks, set `REPO_HEALTH_QUEUE_BACKEND=memory`. Production
uses `REPO_HEALTH_QUEUE_BACKEND=sql` and an injected
`REPO_HEALTH_DATABASE_URL`. The worker configuration also accepts
`REPO_HEALTH_WORKER_ID`, `REPO_HEALTH_MAX_CONCURRENCY`,
`REPO_HEALTH_TASK_TIMEOUT_SECONDS` and `REPO_HEALTH_LEASE_SECONDS`.

Readiness is fail-closed for invalid configuration or unavailable required
database/queue dependencies. It does not claim provider availability merely
because the process is alive. Queue delivery is at-least-once: claim/lease,
retry, dead-letter and idempotent envelope persistence happen before ack.

Operational limits include bounded repository/analyzer concurrency, task
deadline, facts/output caps and redacted structured telemetry. A single
analyzer failure produces a visible partial result; request, collection, score
or persistence failure fails the envelope.

Split an analyzer into a network service only after measured queue pressure,
repository size, provider rate limits or tenant-isolation requirements justify
the operational cost. The contract and worker boundary already permit this
without changing analyzer business logic.
