# Repository Health Analyzer

Repository Health Analyzer turns the state of an open-source repository checkout
into an explainable Repo Health Score from 0 to 100. It exposes canonical health
reports, evidence, limitations, recommendations, ranking, comparison, history,
replay/rescore, and related API/CLI/MCP/UI surfaces.

## Current product boundary

- Python API/CLI/server packages provide repository ingestion, analysis, facts,
  persistence, scoring, projections, and service boundaries.
- The web application provides the user-facing health report and public ranking
  surfaces.
- `RepoWise` and other external or vendored projects are current implementation
  dependencies/sources, not the desired long-term application boundary.
- The current setup task is infrastructure-only. No product refactor is part of
  this baseline.

## Compatibility invariants

- The canonical repository score remains `0..100`.
- Missing or unavailable evidence is represented by explicit status/limitations,
  not silently converted to a negative score or score zero.
- Public responses must not expose local paths or raw evidence that is not meant
  for public consumers.
- Existing fixtures, replay behavior, API contracts, CLI behavior, and UI flows
  are protected until a migration proves parity or improvement.

See `.ai-factory/ARCHITECTURE.md` for the current map and `.ai-factory/RULES.md`
for the permanent change policy.
