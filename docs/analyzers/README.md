# Analyzer boundaries

Each analyzer consumes `AnalyzerInput` with normalized `RepositoryFacts` and
returns one versioned `CategoryResult`. No analyzer imports FastAPI, ORM
models, UI code, raw SourceCraft payloads or another analyzer.

| Category | Canonical ID | Policy/source |
| --- | --- | --- |
| Documentation | `repo-health.documentation` | Vale + documentation-calibration-v2 |
| Activity | `repo-health.activity` | Git/PyDriller + activity-calibration-v2 |
| Issues | `repo-health.issues` | SourceCraft Issues + partial-component policy |
| CI/CD | `repo-health.cicd` | SourceCraft CI + calibration-v2 |
| Security | `repo-health.security` | SourceCraft AppSec REST + security-v1 |
| Code Health | `repo-health.code-health` | SonarQube, git-sizer, Git and TODO facts |

Compatibility IDs remain at the health edge only and are converted one-way to
these six categories.
