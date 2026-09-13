# Repository Health Analyzer — agent contract

This repository is being modularized incrementally. Before changing product code,
read `.ai-factory/DESCRIPTION.md`, `.ai-factory/ARCHITECTURE.md`, and
`.ai-factory/RULES.md`.

The durable workflow is:

`explore → plan → improve → implement → verify → review`

Product behavior is protected by the existing implementation and its fixtures.
Do not remove or silently replace legacy behavior until the replacement is tested,
compared against the baseline, and shown to be equivalent or better.

Keep serious work on the task branch/worktree created by Handoff. Keep unrelated
files and functionality unchanged.
