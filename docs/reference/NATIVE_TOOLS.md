# Native and copied tool reference

All commits below are authoritative in `vendor/SOURCES.lock`. Commands use
paths relative to the workspace root. `bin/` contains generated build outputs;
it is not a source snapshot and must never replace the pinned tree.

| Source / commit | Copied path | Build/test | Adapter / output |
| --- | --- | --- | --- |
| [OpenSSF Scorecard](https://github.com/ossf/scorecard) `f92023a3f77879f96e0c9c1305f289d755be4bb6` | `vendor/scorecard` | `go test ./...`; `go build -buildvcs=false -o ../../bin/scorecard .` | `scorecard.local`; JSON from `--format json --show-details`; checks and evidence |
| [RepoHealth](https://github.com/spbuilds/repohealth) `a62f96a00134e7f08541fa00dd962666222394f8` | `vendor/repohealth` | `go test ./...`; `go build -buildvcs=false -o ../../bin/repohealth ./cmd/repohealth` | `repohealth.baseline`; deterministic JSON checks |
| [Criticality Score](https://github.com/ossf/criticality_score) `0e76c6a99d865dddcbd89dff4117f0a54b1abfb8` | `vendor/criticality_score` | `go test ./...`; `go build -buildvcs=false -o ../../bin/criticality-score ./cmd/scorer` | `criticality.importance`; CSV input/output; separate priority context |
| [Qlty](https://github.com/qltysh/qlty) `338acb3405a966151cd9e29685f2a8eb71d92434` | `vendor/qlty` | `cargo test --workspace`; `cargo build --release --package qlty` | `qlty.check`; SARIF/rdjson; plugin planning and batching remain upstream |
| [Sokrates](https://github.com/zeljkoobrenovic/sokrates) `f400eb7235a755146e854a1bf4bd90cbe1ee5086` | `vendor/sokrates` | `mvn -pl cli -am test package` | `sokrates.analysis`; `data/analysisResults.json`; language-aware measures |
| [SonarQube](https://github.com/SonarSource/sonarqube) `2697822f855fb0e4b8a09f720327095c04f0a2a8` | `vendor/sonarqube` | `./gradlew :sonar-duplications:test :sonar-core:test` | Copied/verified duplication and SARIF primitives; no standalone SonarQube analyzer ID is claimed |

## Common adapter boundary

`packages/core/src/repowise/core/analysis/health/integrations/native_adapters.py`
keeps each upstream output format intact, parses it into the common
`AnalyzerResult`, and records source commit/tool version, evidence and bounded
limitations. `process.py` resolves `bin/<tool>` or `bin/<tool>.exe`, passes an
allow-listed environment, enforces timeout/output caps and never uses a shell.

Native outputs are inputs to the common analyzer envelope, not independent
public scores. Their normalized dimensions are composed by the canonical
health policy; skipped, unavailable and parser-error results remain visible
and cannot silently become a passing measurement. Scorecard, RepoHealth and
Criticality are Go tools; Qlty is Rust; Sokrates and selected SonarQube
duplication primitives are Java. Qlty/Sokrates/SonarQube are optional or
primitive/report inputs for the default local runtime, while the bounded Go
tools are the required composition binaries.

Configured defaults are in `config/analyzers/native-tools.yaml`:

- process timeout: 120 seconds (180 for Sokrates);
- stdout/stderr cap: 16 MiB per process and report cap: 64 MiB;
- max files: 50,000; max commits: 10,000;
- max concurrent native processes: 2; retry budget: 1;
- cache TTL: 24 hours; stale threshold: 48 hours; stale results remain visible;
- history tiers: recent for fast, all for full/backfill, changed files for diff.
- public ranking: only committed snapshots with fresh, rankable mode and at
  least 50% evidence coverage are eligible; tool absence is a visible skip.

## Forge and data sources

RepoCrunch, CollectOSS, Perceval, ELK, SortingHat, SirMordred, Graal and
Sigils are copied under `vendor/repocrunch`, `vendor/collectoss` and
`vendor/chaoss/*`. Their exact commits and tests are listed in
`vendor/SOURCES.lock`. Forge limits live in `config/analyzers/forge.yaml`:
ETag cache, 24-hour TTL, 48-hour stale threshold, 100-page cap, two concurrent
requests and a bounded retry budget. A 401/403/404 becomes an explicit unknown
or skipped capability state.

## Reference-only products

- [CodeScene](https://codescene.com/) — `reference-only`: no copied source,
  commit or executable adapter. We use its hotspot-first product concept only.
- [repohealth.tools](https://repohealth.tools/) — `reference-only`: no copied
  source, commit or executable adapter. No source-level integration is implied.

## Updating a pinned source

1. Update the source to an explicit 40-character commit and copy the whole
   source tree/package tree into the declared `vendor/` path.
2. Update the matching `vendor/SOURCES.lock` entry and retain upstream sentinels.
3. Run `uv run python scripts/vendor_sources.py --verify`.
4. Run `uv run python scripts/verify_source_update.py` to prove a drifted
   temporary ledger is rejected before build.
5. Run the source's native build/test command and the matching adapter golden
   tests.
6. Run `make health-replay`; review the bounded semantic diff. Do not blanket
   regenerate golden data.
7. Record new toolchain requirements or platform skips in this document and
   the CI artifact summary.
