# Repo Health research archive

This directory contains audit evidence, behavior baselines, calibration
provenance, legal inventories and cleanup decisions. It is not a runtime
module and must not be imported or packaged as production code.

Every retained report should state its source revision, tool/policy version,
digest, redaction status and reproduction command. Raw provider payloads,
tokens and unredacted live output are not accepted here.

Key records:

- `repo-health-audit-baseline.*` — graph, registry and scope baseline;
- `repo-health-behavior-baseline.json` — frozen score/parity behavior;
- `repo-health-external-dependencies.json` — dependency/license matrix;
- `repo-health-reachability-ledger.md` — cleanup proof and dispositions;
- `repo-health-cleanup-quarantine.md` — reversible local artifact cleanup.
