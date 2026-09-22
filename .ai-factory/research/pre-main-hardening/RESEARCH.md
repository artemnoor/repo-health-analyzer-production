# Research: Pre-main production hardening

Updated: 2026-09-22 03:15
Status: active
Index: [INDEX.md](INDEX.md)

## Active Summary (input for /aif-plan)
<!-- aif:active-summary:start -->
Topic: Pre-main production hardening
Goal: Make public versus owner-extended assessment context, Yandex ID versus SourceCraft PAT boundaries, AppSec scan states, and contributor identity uncertainty explicit without changing the frozen scoring behavior.
Scope: Versioned request/facts/result contracts, profile-aware SourceCraft collection, AppSec normalization and analyzer degradation, Git/PyDriller contributor evidence, API/worker parity tests, docs, and strict verification. Out of scope: Recommendation Engine, frontend redesign, leaderboard implementation, new scoring formulas, weights, calibration-v2, security caps, and broad persistence migrations.
Constraints: Preserve the existing six-analyzer pipeline and 129-test baseline; keep missing/unavailable/partial/inconclusive distinct from numeric zero; do not persist or log PAT values; do not use Yandex ID tokens as SourceCraft credentials; do not merge contributor identities heuristically; keep work on the current task branch and preserve unrelated uncommitted validation-lab changes.
Requirements: Add typed AssessmentProfile values PUBLIC and OWNER_EXTENDED; carry profile, used sources, capability states, and safe authorization metadata through AnalysisRequest, RepositoryFacts, AnalyzerInput, CategoryResult, RepoHealthResult, and persistence envelope semantics. PUBLIC must not consume owner-authorized SourceCraft Issues/CI/AppSec data or require a PAT. OWNER_EXTENDED may consume configured SourceCraft data through the existing common client. Add typed AppSec states NO_SCAN, FINISHED_ZERO_FINDINGS, FINISHED_WITH_FINDINGS, FAILED, UNAVAILABLE, and PARTIAL where needed; ensure only finished states can produce numeric Security results. Preserve contributor formula arithmetic while exposing deterministic identity policy and ambiguity/uncertainty without email persistence or aggressive merge.
Decisions: Use one ScoreEngineV1 and the same six analyzers for both profiles; the profile changes eligible facts and context, not formulas. Treat SourceCraft PAT as transport authorization only and represent only boolean presence/safe scopes in contracts. Keep Yandex ID as an optional trusted identity subject injected by an upstream auth layer; the current API must not accept arbitrary user identity claims. Use SourceStatus plus typed capability context for provider availability, and store scan state in normalized SecurityFacts without raw payloads. Use Git name/email only in bounded in-memory PyDriller collection to detect ambiguity; retain existing contributor counts for formula parity and emit policy/uncertainty facts instead of guessing merges.
Risks: A profile-aware collector path can accidentally change default analysis behavior; all existing default requests must remain PUBLIC and parity fixtures must prove unchanged math. Adding metadata to frozen JSON contracts can affect digests and persistence comparisons, so canonical serialization and API/worker parity must be tested. AppSec zero findings must not be confused with no scan, and failed scans must never become Security 0 or 100. SourceCraft API may not expose stable contributor IDs, so identity uncertainty must remain explicit.
Open questions: Whether a future SourceCraft API exposes stable contributor/user IDs; whether Yandex ID authentication will be added before UI work; whether SourceCraft Issues/CI/AppSec endpoints are ever public-compatible. None of these are required to complete this hardening if the contracts preserve the distinction.
Success signals: Default public analysis runs without SourceCraft PAT; owner-extended controlled fixtures increase provider coverage only when authorized; API and Worker projections match; all five AppSec state fixtures map to explicit normalized state and safe CategoryResult; contributor variant tests show no automatic merge; ScoreEngineV1 and golden fixtures are unchanged; full strict gates and final report pass.
Next step: Create an ultra implementation plan for the contract-first hardening, implement in reversible phases, verify every phase, then review before recommending commit/merge.
<!-- aif:active-summary:end -->

## Sessions
<!-- aif:sessions:start -->
- 2026-09-22: Read the supplied hardening specification and current project context; inspected request/result contracts, SourceCraft collectors, AppSec analyzer, PyDriller collector, orchestration, API, Worker, and JSON persistence. Identified four concrete gaps and confirmed no SQL migration is required.
<!-- aif:sessions:end -->
