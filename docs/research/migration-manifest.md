# Extraction migration manifest

This manifest records the controlled cleanup groups. Each group was checked
against the target import closure and the target parity suite before deletion.

| Path/group | Decision | Evidence | Rollback |
| --- | --- | --- | --- |
| `packages/` | delete after final cutover | target imports use `src/repo_health`; API/worker/package gates | revert deletion commit |
| `website/` and frontend package roots | delete | backend API tests have no frontend route or package imports | revert deletion commit |
| `vendor/` and `.sources/` | delete | adapters use installed tools/services; no target import | restore from pre-extraction commit; notices retained |
| `spikes/` and generated artifacts | delete/archive | methodology and calibration conclusions retained here | restore from pre-extraction commit |
| legacy tests/fixtures | delete | target unit/contract/adapter/integration/golden/E2E suite replaces symbols | restore from pre-extraction commit |
| broad server/core scripts | delete | no target entrypoint or import closure | restore from pre-extraction commit |
| generic editor/agent assets | delete from product | runtime/package/Docker scans are independent | retain outside product checkout |

The root AGPL-3.0 license remains because the retained analyzer and score
behavior are derived from the original repository. External dependency notices
are listed in `THIRD_PARTY_NOTICES`.
