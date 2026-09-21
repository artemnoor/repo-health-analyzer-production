# Hercules spike

Verdict: **PARTIAL FIT** for activity analytics.

Hercules produced a rich YAML activity report from the real fixture, including
developers, burndown, per-file history, and commit statistics. The practical
Windows path used the official release binary because the exact source checkout
does not build with the current Go toolchain on this host.

## Source and license

- Upstream: `https://github.com/src-d/hercules.git`
- Cloned at: `68bb211faaedeffb53e799ab89e2aa48d8cb0ad3`
- Probe executable: official upstream Windows release `v10.7.2`
- License: Apache-2.0 (`upstream/LICENSE.md`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Install and build

The source build was attempted with Go `1.26.2` and failed in the old
`go-tree-sitter`/internal rbtree dependency (`Node undefined` and
`CompressUInt32Slice undefined`). The failure is recorded in
`runs/build.timing`. The official release archive was then extracted to
`runs/hercules-10.7.2/`; `hercules.exe version` succeeds there.

## Fixture run

The run used all fixture refs from `runs/all-commits.txt` and enabled
`--burndown --burndown-people --devs --file-history --commits-stat`. It exited
`0` in `0.172 s` (`runs/fixture.timing`) and wrote structured YAML to
`runs/fixture.yaml`.

Key output:

```text
commits: 13
people: 3
burndown project: 237 lines
burndown people: 15 / 97 / 125 lines
developer time bins: 3
```

The YAML also contains language/file statistics, per-commit file changes, and
developer identity strings. A missing-repository probe exits `2` and emits a
panic stack trace (`runs/missing_repo.stderr.log`), so the adapter should
normalize process failures rather than expose raw stderr directly.

## Integration boundary

The integration boundary is a CLI subprocess with a checked-out Git path and a
commit-list policy. YAML parsing is required; the selected analysis flags
should be explicit because they control report size and cost. A release-binary
bundle is the current deployment option for Windows. The source checkout can
be revisited after pinning a compatible Go/dependency toolchain.

## Runtime, complexity, and limitations

The analyses traverse commit history, diffs, file history, and language
statistics, so time and memory grow with reachable history and changed-file
volume. The tiny fixture completes quickly, but burndown and file-history
reports can become large. The source-build failure and the raw panic-style
missing-path error make Hercules less portable and less adapter-friendly than
PyDriller, despite the useful activity output.
