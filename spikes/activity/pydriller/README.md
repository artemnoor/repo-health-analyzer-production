# PyDriller spike

Verdict: **GOOD FIT** for repository history and change-activity extraction.

PyDriller runs directly as a Python library and exposes commits, authors,
branches, modifications, line changes, diffs, and process metrics. The custom
runner below converts those objects into stable JSON suitable for an analyzer
adapter.

## Source and license

- Upstream: `https://github.com/ishepard/pydriller.git`
- Cloned at: `a527c83ba81ee949cb84b977c155f337423743be`
- Installed package: PyDriller `2.12` from the exact clone
- License: Apache-2.0 (`upstream/LICENSE`, `upstream/setup.py`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Install and standard API

The exact clone was installed into `spikes/activity/pydriller/.venv` and
imported through the normal `pydriller.Repository` API. The reproducible spike
runner is `run_pydriller.py`; it calls `Repository(...,
include_refs=True, include_remotes=True, order="date-order").traverse_commits()`
and uses the built-in `CommitsCount`, `LinesCount`, and `ContributorsCount`
process metrics.

## Fixture run

The fixture was analyzed across its local and remote refs. The JSON report is
`runs/fixture.json`; the command's wall time was `3.183 s` and the runner also
records its internal runtime in the report.

Observed values:

```text
commit occurrences across refs: 13
unique commits:                 13
authors:                         3
merge commits:                   0
empty commits by files:          0
insertions / deletions:        255 / 18
total churn:                   273
modified-file records:           22
change types:             ADD=11, MODIFY=11
process metric errors:            {}
```

The report also contains first/last author and committer timestamps, author
counts, branch membership, per-file insertion/deletion/churn, diff previews,
and process metrics grouped by fixture file. The result is structured JSON;
the missing-repository probe returns a structured error object and exits `1`
with `NoSuchPathError` (`runs/missing_repo.stdout.log`).

## Integration boundary

The preferred boundary is an in-process Python adapter that constructs a
`Repository` for a checked-out path and maps `Commit`/`Modification` fields to
the repository-health contract. The spike's JSON runner demonstrates a stable
serialization boundary when the host process should remain isolated.

One important semantic choice is ref scope. The top-level activity numbers
include local and remote refs, so an integration must decide whether to
deduplicate by commit hash, analyze only the default branch, or intentionally
measure all reachable refs. The built-in process metric classes were run over
the fixture's observed author-date interval and do not themselves provide the
same all-ref report shape.

## Runtime, complexity, and limitations

Traversal is proportional to reachable commits and changed-file/diff volume;
retaining diffs and previews increases memory use. The fixture is small, so the
3.183-second wall time mostly reflects Python and Git startup. Large histories
should stream or cap diff materialization. PyDriller is otherwise a clean
library-level fit with no service or database requirement.
