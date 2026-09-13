# Modularization roadmap

This roadmap records future work only; setup does not start implementation.

## Next candidate: Analyzer Integration Core

Preparation command:

`/aif-explore ultra Analyzer Integration Core`

Research targets include `AnalyzerContext`, `AnalyzerDefinition`,
`AnalyzerResult`, `AnalyzerStatus`, `Finding`, `EvidenceRef`, `MetricValue`,
`Limitation`, registry, runner, orchestrator, process boundaries, adapters, and
lifecycle. Any extraction must follow the permanent rules in `RULES.md`, retain
the old implementation for comparison, and use the task template in
`templates/analyzer-integration-core.md`.
