# SourceCraft Repository Health Analyzer

This repository is a backend-only Python service that collects SourceCraft and
Git facts, runs six isolated health analyzers, calculates the frozen Repo Health
Score v1, persists immutable results, and exposes a small REST API plus scheduled
background execution.

## Product boundary

- Runtime code lives in `src/repo_health`.
- Contracts are versioned, typed Pydantic models and are transport-neutral.
- Analyzer business logic does not import FastAPI, database implementations, or
  another analyzer's internals.
- External engines are optional adapters/process dependencies: Vale, PyDriller,
  SonarQube, and git-sizer.
- The repository intentionally contains no frontend, Node workspace, MCP server,
  agent product, or copied upstream repository.

## Compatibility invariants

- Documentation, Activity, Issues, CI/CD, Security, and Code Health behavior is
  protected by golden calibration-v2 fixtures.
- Repo Health Score v1 weights, K thresholds, and security caps are frozen.
- Evidence, coverage, confidence, partial results, unavailable inputs, and
  correlation IDs remain explicit in serialized results.
- One analyzer failure must not discard successful categories from an analysis.
- Legacy behavior may be removed only after parity and clean-checkout gates pass.

See `.ai-factory/ARCHITECTURE.md` for the target map and `.ai-factory/RULES.md`
for the permanent change policy.
