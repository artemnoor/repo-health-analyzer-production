# CHAOSS Metrics spike

Verdict: **PARTIAL FIT AS A METHODOLOGY REFERENCE; NOT A RUNTIME TOOL**.

This exact upstream is a standards and metric-definition repository, not a
collector or executable issue analyzer. It provides a metric template and
project guidance, but the cloned commit contains no implementation for issue
response time, resolution duration, issue age, quantiles, or bot filtering.

## Source and license

- Upstream: `https://github.com/chaoss/metrics.git`
- Cloned at: `fae1f4dfc533a6f28499bdba3fb1514ccabc2018`
- License: MIT (`upstream/LICENSE` and `upstream/README.md`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## What was actually present

The exact tree contains `README.md`, `resources/metrics-template.md`, quality
checklist/release guidance, and the MIT license. The tree and the fixture
availability scan are recorded in `runs/reference-scan.txt`. There is no
`package.json`, Python package, CLI, SQL implementation, API server, or fixture
issue-event export to execute.

The metric template is still useful for designing the adapter contract. It
requires a question, description, objectives, implementation details, filters,
visualizations, tools providing the metric, data-collection strategies,
references, and contributors. It also explicitly calls out privacy/data-ethics
and provider terms-of-service risks.

## Requested issue metric mapping

For this commit, the honest status is:

| Metric | Algorithm in this clone | What an implementation must define |
| --- | --- | --- |
| Issue response time | Not present | issue creation, first non-author response, bot policy, unresolved fallback, time unit |
| Resolution duration | Not present | opened/closed event pairing, reopened behavior, closed-only filter, unit |
| Issue age | Not present | observation time, open interval, treatment of unresolved issues |
| Quantiles | Not present | quantile definition/interpolation and empty/sparse periods |
| Bots | Not present | identity/type filter, whether bots are excluded from each metric |

The table is a gap analysis, not a claim that CHAOSS defines no such metrics
elsewhere. The exact cloned repository delegates published metric work to
working-group releases and linked repositories; those additional sources were
not silently substituted for the requested exact upstream.

## Run and integration boundary

There is no standard executable run. The practical integration is a
specification-to-implementation mapping: choose a data provider (for example,
GitHub events or an existing analytics backend), document the event semantics
under the template, and expose the resulting time series and methodology in a
separate adapter. CHAOSS contributes vocabulary, questions, filters, ethical
constraints, and review structure; it does not ingest the current fixture.

No fixture metrics, runtime, structured output, or error code are claimed. The
fixture contains a CI YAML and source files but no issue tracker event stream.
OpenDigger's adjacent spike contains an executable reproduction of one concrete
implementation of the requested algorithms, but that is intentionally reported
separately from this CHAOSS reference.
