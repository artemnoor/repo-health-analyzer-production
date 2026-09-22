<!-- aif:research-mode:ultra -->
# Research Index: Pre-main production hardening

Topic: Pre-main production hardening
Slug: pre-main-hardening
Updated: 2026-09-22 03:15
Status: active

## Purpose

Establish evidence-backed contracts and boundaries for public versus owner-extended assessments, credential domains, AppSec scan states, and contributor identity before merging the current backend branch.

## Artifact Index

| Artifact | Purpose | Why included | Status |
|----------|---------|--------------|--------|
| [RESEARCH.md](RESEARCH.md) | Active findings, constraints, and open questions | Required ultra research summary | active |
| [C4-CONTEXT.md](C4-CONTEXT.md) | Trust boundary between user identity, SourceCraft access, and analysis | The task crosses Yandex ID, SourceCraft PAT, public data, and owner-authorized data | active |
| [C4-CONTAINER.md](C4-CONTAINER.md) | Runtime containers and data ownership | API, worker, collection, analyzers, persistence, and external providers participate | active |
| [C4-COMPONENT-analysis-contracts.md](C4-COMPONENT-analysis-contracts.md) | Profile, capability, AppSec, and identity contract relationships | More than three internal components have materially coupled semantics | active |
| [DEPENDENCY-GRAPH.md](DEPENDENCY-GRAPH.md) | Evidence-backed dependency direction and change impact | Profile and scan-state context crosses request, collection, analyzer, scoring, and persistence boundaries | active |
| [ADR-0001-assessment-profile-context.md](ADR-0001-assessment-profile-context.md) | Preferred single-engine assessment-profile decision | The public/owner distinction is material and costly to reverse after leaderboard/API consumers exist | proposed |

## Reading Order

1. [RESEARCH.md](RESEARCH.md)
2. [C4-CONTEXT.md](C4-CONTEXT.md)
3. [C4-CONTAINER.md](C4-CONTAINER.md)
4. [C4-COMPONENT-analysis-contracts.md](C4-COMPONENT-analysis-contracts.md)
5. [DEPENDENCY-GRAPH.md](DEPENDENCY-GRAPH.md)
6. [ADR-0001-assessment-profile-context.md](ADR-0001-assessment-profile-context.md)

## Traceability

| ID | Finding / requirement | Evidence | Decision or artifact |
|----|-----------------------|----------|----------------------|
| REQ-001 | Public and owner-extended analyses need explicit typed context | `src/repo_health/contracts/requests.py`, `src/repo_health/contracts/results.py` | [ADR-0001](ADR-0001-assessment-profile-context.md) |
| REQ-002 | SourceCraft PAT must remain an adapter credential, not user identity or domain data | `src/repo_health/collection/sourcecraft.py`, `src/repo_health/config.py`, `docs/sourcecraft.md` | [C4-CONTEXT](C4-CONTEXT.md) |
| REQ-003 | AppSec no-scan, finished-zero, finished-findings, failed, and unavailable must be distinguishable | `src/repo_health/collection/sourcecraft.py`, `src/repo_health/analyzers/security/analyzer.py` | [C4-COMPONENT](C4-COMPONENT-analysis-contracts.md) |
| REQ-004 | Contributor counting must not silently merge identities | `src/repo_health/collection/git/pydriller.py` | [DEPENDENCY-GRAPH](DEPENDENCY-GRAPH.md) |
