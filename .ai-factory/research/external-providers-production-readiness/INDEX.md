# External Providers Production Readiness Research

<!-- aif:research-mode:ultra -->

## Scope

Evidence-first research for the production-readiness checkpoint in
`goal-objective.md`. This bundle covers Docker/SonarQube runtime readiness,
official SourceCraft REST contracts, current production composition, external
tool capability detection, and the smallest safe implementation boundary.

## Research files

- [Research report](RESEARCH.md)
- [Runtime dependency graph](DEPENDENCY-GRAPH.md)

## Active Summary

- The repository is already on a dedicated task branch with intentional
  uncommitted validation-lab changes; those changes must be preserved.
- Baseline test suite is green: `119 passed`.
- Native SonarQube 26.9.0.129388 is running at `http://127.0.0.1:9000` and
  reports `UP`; Docker Desktop is not usable because its daemon never creates
  the Linux engine pipe and `dockerd` fails during startup.
- SourceCraft CLI authentication is available through the configured local
  auth session. The controlled organization is `artem03102006`; the private
  fixture `repo-health-calibration-issues` is available and has real issues.
  A separate CI fixture exists, but the current production code does not yet
  call the official Issues/CI endpoints.
- Official SourceCraft REST paths are confirmed as
  `/repos/{org_slug}/{repo_slug}/issues` and
  `/repos/{org_slug}/{repo_slug}/cicd/runs`, both with page-token envelopes.
  Deprecated non-`/repos` CI paths must not be used.
- Current runtime wires Git, PyDriller, Vale, TODO-history, git-sizer and
  optional SonarQube, plus SourceCraft AppSec. Issues and CI/CD are currently
  deliberately wired as unavailable placeholders even when SourceCraft is
  configured.
- Existing scoring, calibration-v2, contracts, persistence and analyzers are
  protected by the green baseline and must not be rewritten.
- The intended change is additive and bounded: official SourceCraft Issues and
  CI/CD adapters, canonical runtime wiring, safe PAT environment compatibility,
  live Sonar scanner evidence, targeted tests, and readiness documentation.
