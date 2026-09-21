# Doc Detective spike

Verdict: **PARTIAL FIT** for the repository-health analyzer.

Doc Detective is a documentation test runner. It can resolve documentation into
test specifications and execute `runShell`, `runCode`, `checkLink`, browser, and
HTTP actions, then emit terminal, JSON, HTML, JUnit, Markdown, or run-folder
reports. It is useful for executable documentation, but an ordinary Markdown
file is not automatically a valid test specification.

## Source and license

- Upstream: `https://github.com/doc-detective/doc-detective.git`
- Cloned at: `dc88004aded21ddcd03db5b489204baf6ea30e6a`
- Package version: `4.38.4`
- License: `AGPL-3.0-only` (declared by `upstream/package.json` and `upstream/LICENSE`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Install and build

The standard install was `npm ci` in the exact clone. It completed in about
39.0 seconds and installed 1664 packages. npm reported 30 audit findings during
the install (1 low, 9 moderate, 20 high). The package asks for Node
`^22.22.0 || >=24.0.0`; this host has Node `22.13.0`, so npm emitted an
engine warning.

The standard `npm run build` did not complete because the nested npm process on
Windows could not resolve `node` (`'node' is not recognized`). The equivalent
build subcommands succeeded when invoked with the absolute Node executable:

```text
cd src/common; npm run build
node node_modules/typescript/bin/tsc
node scripts/createCjsWrapper.js
npm run copy:schemas
```

The resulting `dist/index.js` and `dist/index.cjs` were used for the runs.
See `runs/build-manual.timing` for the build evidence and limitation.

## Fixture runs

### Ordinary README input

Command shape:

```text
node upstream/bin/doc-detective.js --config=.doc-detective.json \
  --input=../../_fixture/codex-external-audit-public-20260916/README.md \
  --output=runs/fixture-output --reporters terminal json runFolder \
  --no-auto-update --no-hints --shell cmd
```

Observed result:

- exit code: `0`
- wall time: `5.812 s` (`runs/fixture.timing`)
- no tests were resolved; the README was reported as not creating a valid test
  specification
- the JSON reporter wrote `null` for the top-level result because no test ran;
  the run-folder reporter still created HTML/JSON artifacts under
  `runs/fixture-output/.doc-detective/runs/`

This is an important negative result: a normal repository README cannot be
treated as executable documentation without Doc Detective-specific markup or a
sidecar specification.

### Executable sidecar against real fixture files

`fixture-executable.spec.json` runs three actions against the real fixture:

1. `python -m py_compile appsec_readback.py`;
2. `node --check redirect-fixture.js`;
3. a JavaScript `runCode` assertion that checks `redirect-fixture.js` exists.

The run used `--allow-unsafe --shell cmd` and the JSON/run-folder reporters.
All three steps passed:

```text
specs: 1 passed, 0 failed
tests: 1 passed, 0 failed
steps: 3 passed, 0 failed
```

The wall time was `8.592 s` (startup included); the tool's structured result
reports `durationMs: 361` for the executed spec. See
`runs/executable-output/.doc-detective/runs/*/testResults.json` and
`runs/executable.timing`.

### Failure case

Using `--config=runs/missing.ini` exits with code `1` and reports both the
missing file and the unreadable configuration in
`runs/invalid-config.stderr.log`. Its timing is in
`runs/invalid-config.timing`.

## Integration boundary

The practical boundary is a subprocess CLI. The adapter would provide an input
specification/configuration, run the CLI, parse the JSON reporter output, and
retain the HTML/run-folder artifact path for humans. There is no required
server or database for the shell/code path. Link, HTTP, and browser checks add
network/browser dependencies and should remain opt-in.

The custom `.doc-detective.json` disables telemetry and declares a Markdown
link extraction rule. The rule did not turn the fixture README into a valid
specification, so it should not be treated as a general Markdown linter.

## Runtime and failure surface

Startup and dependency installation are relatively heavy for a documentation
check. The sidecar run itself was sub-second inside the tool, while Node startup
and configuration resolution made the end-to-end command 8.6 seconds on this
host. `--allow-unsafe` is required for shell/code execution. Warnings are
non-fatal by default; use `--exit-on-fail` when a CI gate must fail on test
failures. The current source also emits many Ajv strict-schema warnings on
stderr even when the run passes.

The AGPL-3.0-only license is the main adoption constraint. The tool is viable
as an isolated CLI integration for executable documentation, but the README
behavior and license mean it is not a drop-in documentation-health analyzer.
