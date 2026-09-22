# Analyzer boundaries

Each analyzer accepts one `AnalyzerInput` containing normalized facts and emits
one deterministic `CategoryResult`. The result includes score, findings,
evidence references, coverage, confidence, limitations and source versions.

| Category | Normalized input | Production adapter/policy |
| --- | --- | --- |
| Documentation | documentation facts | Vale findings + calibration-v2 |
| Activity | Git/PyDriller facts | commit, author and recency policy |
| Issues | SourceCraft issue facts | partial-component policy |
| CI/CD | SourceCraft CI facts | calibration-v2 reliability policy |
| Security | SourceCraft AppSec facts | REST-only severity penalties and caps |
| Code Health | SonarQube, git-sizer, Git/TODO facts | calibration-v2 component policy |

External engines are called through collection adapters or process boundaries;
their source trees are not part of the production package. An analyzer may be
run through `LocalExecutor` or a serialized worker without changing its
business logic.

Activity keeps the existing calibration-v2 inputs (`unique_commits`, recent
commits and author counts) unchanged. PyDriller additionally performs a
bounded in-memory sanity check using normalized author name/email pairs. It
reports a policy, ambiguity and confidence metadata, but never merges names,
emails or contributor identities heuristically and never persists email
addresses.

Security consumes only the normalized SourceCraft AppSec state and severity
facts. It does not substitute a local scanner for AppSec and does not turn
missing lifecycle evidence into a numeric zero.
