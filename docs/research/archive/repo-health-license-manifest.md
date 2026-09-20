# Repo Health copied-source license manifest

This manifest is derived from `vendor/SOURCES.lock` and the local
`LICENSE*`, `NOTICE*` and `COPYING*` files. The checkout contains 65 matching
legal files. A missing `.sources` root is recorded as an unresolved provenance
state; it is never interpreted as permission to delete the corresponding
vendor tree or notice. The roots were materialized during Phase 7. The current
source gate passes all pinned trees except `vendor/collectoss`, whose tracked
copy has content drift against the pinned source commit and therefore remains
a legal and reachability blocker.

| dependency | copied/source path | license observed | notice/license files | production required | can delete local copy now |
| --- | --- | --- | --- | --- | --- |
| RepoWise | `.sources/repowise` → repository root | unresolved source root; repository license audit required | source root missing | YES for broader RepoWise product | NO |
| Scorecard | `.sources/scorecard` → `vendor/scorecard` | Apache-2.0 | `vendor/scorecard/LICENSE` plus nested test fixtures | NO for target six | NO; reachability and legal gate pending |
| Criticality Score | `.sources/criticality_score` → `vendor/criticality_score` | Apache-2.0 | `vendor/criticality_score/LICENSE` | NO for target score; possible auxiliary context | NO |
| RepoHealth | `.sources/repohealth` → `vendor/repohealth` | MIT | `vendor/repohealth/LICENSE` plus testdata license | NO for target six | NO |
| Qlty | `.sources/qlty` → `vendor/qlty` | Business Source License 1.1 | `vendor/qlty/LICENSE.md` | NO for target Code Health | NO; BSL review required |
| Sokrates | `.sources/sokrates` → `vendor/sokrates` | MIT | `vendor/sokrates/LICENSE` | NO for target Code Health | NO |
| SonarQube | `.sources/sonarqube` → `vendor/sonarqube` | LGPL-3.0 observed | `LICENSE.txt`, `NOTICE.txt`, nested `COPYING` | NO as copied source; external service adapter remains | NO; adapter/package audit pending |
| RepoCrunch | `.sources/repocrunch` → `vendor/repocrunch` | MIT | `vendor/repocrunch/LICENSE` | CONDITIONAL for broader dependency/forge surfaces | NO |
| CHAOSS Metrics | `.sources/chaoss-metrics` → `vendor/chaoss/metrics` | MIT | `vendor/chaoss/metrics/LICENSE` | NO runtime requirement; methodology reference | NO until archive attribution decision |
| CollectOSS | `.sources/collectoss` → `vendor/collectoss` | MIT | `vendor/collectoss/LICENSE`, template notice | CONDITIONAL for legacy facts bridge | NO; vendor tree content drift against pinned commit |
| GrimoireLab | `.sources/grimoirelab` → `vendor/chaoss/grimoirelab` | GPL-3.0 observed | `LICENSE`, nested docs license | NO for target six | NO |
| Perceval | `.sources/grimoirelab-perceval` → `vendor/chaoss/perceval` | GPL-3.0 observed | `vendor/chaoss/perceval/LICENSE` | CONDITIONAL for legacy Git/source bridge | NO |
| ELK | `.sources/grimoirelab-elk` → `vendor/chaoss/elk` | GPL-3.0 observed | `vendor/chaoss/elk/LICENSE` | NO for target six | NO |
| SortingHat | `.sources/grimoirelab-sortinghat` → `vendor/chaoss/sortinghat` | GPL-3.0 observed | `vendor/chaoss/sortinghat/LICENSE` | CONDITIONAL for identity compatibility | NO |
| SirMordred | `.sources/grimoirelab-sirmordred` → `vendor/chaoss/sirmordred` | GPL-3.0 observed | `vendor/chaoss/sirmordred/LICENSE` | NO for target six | NO |
| Graal | `.sources/grimoirelab-graal` → `vendor/chaoss/graal` | GPL-3.0 observed | `vendor/chaoss/graal/LICENSE` | NO for target six | NO |
| Sigils | `.sources/grimoirelab-sigils` → `vendor/chaoss/sigils` | GPL-3.0 observed | `vendor/chaoss/sigils/LICENSE` | NO runtime requirement | NO |
| Lychee | `.sources/lychee` → `vendor/lychee` | MIT/Apache-2.0 dual | root and nested example/bench license files | NO for target analyzers | NO; preserve notices until docs audit |
| Documentor | `.sources/documentor` → `vendor/documentor` | Apache-2.0 | `LICENSE.md`, `NOTICE`, `LICENSE-3rdparty.csv` and template | NO for target analyzer | NO; NOTICE preservation pending |
| CodeScene / RepoHealth Tools | reference-only rows in `SOURCES.lock` | no copied code | reference URLs only | NO | YES as references; keep attribution if docs rely on them |

`vendor_sources.py --verify` now verifies the materialized source roots and
reports only the `collectoss` copied-tree drift. The legal cleanup phase must
reconcile that drift with an explicit source/notice decision before any
CollectOSS removal or replacement is treated as complete.
