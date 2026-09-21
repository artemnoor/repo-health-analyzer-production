# Vale spike

Verdict: **GOOD FIT** for repository documentation linting and prose metrics.

Vale is a good subprocess boundary for Markdown and text quality checks. It
produces machine-readable diagnostics and a separate metrics report, while the
fixture contains enough documentation to exercise both paths.

## Source and license

- Upstream: `https://github.com/vale-cli/vale.git`
- Cloned at: `ba6a2c6a725295eb6b7698336d22dec8ffc4af1c`
- Probe executable: official upstream Windows release `v3.22.0`
- License: MIT (`upstream/LICENSE`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Install and build

The exact source clone was inspected and a source build was attempted. The
build did not complete on this host because the current Go `1.26.2` toolchain
could not build the repository's `go-tree-sitter` dependency. The official
`v3.22.0` Windows binary was downloaded from the upstream release and used for
the executable probes. It reports `Vale 3.22.0`.

The spike configures two small local styles in `.vale.ini`: a warning for the
fixture's deliberately imprecise `AWS-shaped` wording and an error-level
`sourcecraft` to `SourceCraft` substitution rule.

## Fixture runs

The fixture README was linted with the local config and JSON output:

- exit code: `0`
- wall time: `0.064 s` (`runs/fixture.timing`)
- one warning at line 3, `RepoHealth.Audit`, matching `AWS-shaped`
- message: `Use a precise description instead of the AWS-shaped wording.`

The JSON report is in `runs/fixture.json`. The warning is intentionally
non-fatal under this configuration; an adapter that treats warnings as a gate
must add an explicit severity policy.

The `ls-metrics` command also produced structured JSON in `runs/metrics.json`:

```text
characters=109, words=19, sentences=2, paragraphs=1,
heading_h1=1, long_words=7, complex_words=5
```

That run took `0.118 s` (`runs/metrics.timing`). A missing config probe exits
with code `2` and emits a structured `E100` error; see
`runs/invalid_config.stdout.log`.

## Integration boundary

The adapter boundary is the Vale CLI. It should pass a repository-relative
file list and config/style directory, parse JSON diagnostics, and optionally
store the metrics JSON. No server, database, or network access is needed once
the binary and styles are provisioned. A parallel per-file invocation is
possible, although one invocation over a file set is simpler and shares the
configuration load.

## Runtime, complexity, and limitations

The successful fixture lint is effectively linear in the bytes of the selected
documents plus style matching. The metrics command is also document-sized;
startup dominates this small sample. The binary probe avoids the source-build
compatibility issue, but release packaging must be managed separately from the
exact source checkout. Vale reports warnings successfully with exit `0`, so
severity-to-gate mapping belongs in the integration layer.
