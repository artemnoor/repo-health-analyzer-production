# Schemathesis spike

Verdict: **PARTIAL FIT / NOT APPLICABLE TO THIS FIXTURE**.

Schemathesis is an adaptive OpenAPI and GraphQL API tester. It generates
requests from an API schema, exercises the target server with Hypothesis, and
checks response properties such as schema conformance and server errors. The
repository-health fixture contains no OpenAPI or GraphQL schema and no API
server, so a real API exploration would require inventing an out-of-scope
service.

## Source and license

- Upstream: `https://github.com/schemathesis/schemathesis.git`
- Cloned at: `94e23b5e497e83404aa681f5443ee32de2c3746f`
- Source version: `4.27.3` (`upstream/pyproject.toml`)
- License: MIT (`upstream/LICENSE` and project metadata)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Fixture inventory

The fixture's YAML files are `.sourcecraft/ci.yaml` and `.semgrep.yml`. The
first is a SourceCraft CI workflow and the second is a Semgrep configuration;
neither has an OpenAPI/Swagger version or GraphQL schema. There are no JSON
schema/API documents and no running endpoint in the fixture. The exact
inventory and keyword search were performed before the run.

## Install and standard run

An isolated Python 3.11 virtual environment was created in `.venv`.
`pip install -e upstream` completed nominally, but the generated Windows
editable launcher could not import `schemathesis` from this non-ASCII workspace
path. Reinstalling the exact source as a regular wheel with
`pip install .\upstream` succeeded and installed the package. Logs and timings
are in `runs/install*.log` and `runs/install*.timing`.

The standard CLI checks then passed:

```text
schemathesis --version       -> schemathesis, version 4.27.3
schemathesis run --help      -> exit 0
```

The help output confirms the integration boundary: a local schema file or URL
plus a required `--url` for file-based schemas, optional worker count and
checks, and JUnit/Harfile/reporting options.

## Real fixture run

The actual SourceCraft workflow YAML was passed as the schema location:

```text
schemathesis run \
  ../../_fixture/codex-external-audit-public-20260916/.sourcecraft/ci.yaml \
  --url http://127.0.0.1:9
```

With `PYTHONUTF8=1` to make the Windows terminal encoding deterministic, the
tool exited `1` after `0.14 s` and produced a structured human-readable error:

```text
Schema Loading Error
Unable to determine the Open API version as it's not specified in the document.
```

See `runs/fixture-utf8.stdout.log`, `runs/fixture-utf8.timing`, and the empty
stderr log. This is a useful negative result: the tool correctly rejects the
fixture's CI YAML before attempting network traffic.

## Failure cases

The same command without `PYTHONUTF8=1` failed earlier while printing the
Unicode header with a Windows `cp1251` `UnicodeEncodeError`; this is captured
in `runs/fixture.stderr.log`. It is an environment/console issue, not a schema
finding. The UTF-8 rerun reached the intended schema validation path.

No generated requests, response metrics, or JSON report are claimed because no
OpenAPI/GraphQL schema was available. To evaluate this tool in a follow-up,
provide a real versioned schema and a reachable test server; then capture
request count, operation coverage, failing examples, response checks, and a
JUnit/JSON-compatible adapter result.

## Integration boundary and runtime

The adapter boundary is a subprocess CLI or Python package call. It needs a
schema, a base URL for local schemas, and usually network access to the target
API. Generation cost grows with the number of operations, parameter domains,
Hypothesis examples, workers, and stateful workflow links; the schema-loading
failure itself was sub-second here. The tool is a strong candidate for API
contract health, but it does not analyze repository activity, issue events, or
CI history by itself.
