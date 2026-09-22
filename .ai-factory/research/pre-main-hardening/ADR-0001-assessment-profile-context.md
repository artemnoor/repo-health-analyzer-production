# ADR-0001: Preserve one scoring engine and carry assessment profile as context

Status: proposed
Date: 2026-09-22
Research: [INDEX.md](INDEX.md)
Decision ID: DEC-001

## Context

The same repository can be analyzed with public Git-derived evidence or with
additional owner-authorized SourceCraft facts. A numeric score without that
context is not comparable for a future public leaderboard. The current code
has one ScoreEngineV1 but no typed profile on requests/results, and SourceCraft
collectors are selected from global capability configuration rather than from
the assessment profile.

## Decision

Add `AssessmentProfile.PUBLIC` and `AssessmentProfile.OWNER_EXTENDED` to the
versioned request/result contracts. Keep one collection/analyzer/ScoreEngineV1
path. PUBLIC requests exclude owner-authorized SourceCraft Issues, CI/CD, and
AppSec facts even when a PAT is configured. OWNER_EXTENDED may use the existing
common SourceCraft client. Carry safe provider capability/source metadata and
the profile through facts, analyzer input, category results, score input, and
final results. Store only credential presence/scopes, never a credential value.

## Alternatives Considered

| Option | Benefits | Costs / risks | Why not selected |
|--------|----------|--------------|------------------|
| Separate public and owner score engines | Explicit behavior per mode | Formula drift, duplicated tests, incomparable semantics | Violates frozen single-engine invariant |
| One engine with implicit capability inference | Small API change | Score context is lost and leaderboard cannot filter safely | Not explicit enough for consumers |
| Profile as typed context around one engine | Preserves parity and provenance | Requires metadata in several contracts | Selected; smallest reversible hardening |

## Consequences

- Positive: public results are reproducible without PAT and owner results retain their observation context.
- Positive: AppSec state and contributor uncertainty can be expressed without changing score arithmetic.
- Negative: serialized contracts and diagnostics gain metadata fields; deterministic tests must include them.
- Follow-up / revisit trigger: add stable SourceCraft contributor IDs only when the official API exposes them and a privacy policy is approved.

## Evidence

- `src/repo_health/contracts/requests.py`
- `src/repo_health/contracts/results.py`
- `src/repo_health/collection/sourcecraft.py`
- `src/repo_health/collection/git/pydriller.py`
- supplied hardening specification in `C:\CodexData\attachments\4b7c10fc-67a1-4ff9-9ba0-65f7fa962b2e\pasted-text-1.txt`
