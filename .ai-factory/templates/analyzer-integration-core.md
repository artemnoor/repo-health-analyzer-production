# Task template: Extract Analyzer Integration Core

Replace `<MODULE>` only after completing the requested exploration. The first
planned module is `Analyzer Integration Core`.

## Prompt

Use the completed `/aif-explore ultra <MODULE>` research as the source of truth.

Extract the existing `<MODULE>` into a self-contained module while preserving all
current behavior.

Requirements:

- Do not delete the old working implementation yet.
- Define explicit input/output contracts and minimal dependencies.
- Identify and preserve AnalyzerContext, AnalyzerDefinition, AnalyzerResult,
  AnalyzerStatus, Finding, EvidenceRef, MetricValue, Limitation, registry,
  runner, orchestrator, process boundaries, adapters, and lifecycle where they
  apply.
- Keep external projects behind replaceable engines/adapters/providers.
- Add or update unit, integration, and regression tests.
- Run old and new implementations against identical fixtures and compare scores,
  evidence, limitations, failure behavior, and output contracts.
- Missing/unavailable data must not become score `0`.
- Do not change unrelated functionality, public contracts, scoring, UI, vendor
  code, or other modules.
- Finish with a concise diff, test evidence, comparison result, and explicit
  follow-up plan for retiring the old path only after parity is proven.
