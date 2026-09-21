# REST API v1

The FastAPI composition root exposes only backend routes:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/healthz` | liveness |
| GET | `/readyz` | bounded readiness/configuration report |
| POST | `/repositories` | register a repository reference |
| POST | `/analyses` | create an idempotent background analysis (202) |
| GET | `/analyses/{analysis_id}` | lifecycle status |
| GET | `/analyses/{analysis_id}/result` | result or 202 while running |
| GET | `/integrations/sourcecraft/status` | non-secret integration status |
| GET | `/scheduler/status` | scheduler state |
| POST | `/scheduler/analyses` | register a periodic analysis job |

Requests and responses map to versioned Pydantic contracts. The public result
contains score breakdown, category results, bounded evidence references,
coverage, confidence and limitations; it does not expose filesystem paths,
raw provider payloads or credentials. `X-Correlation-ID` is returned on every
response.
