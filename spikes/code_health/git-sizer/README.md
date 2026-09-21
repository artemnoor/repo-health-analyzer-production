# git-sizer spike

Verdict: **GOOD FIT** for Git object and repository-size health metrics.

git-sizer is a compact, dependency-light CLI that emits a structured JSON
report over the reachable Git object graph. It is a strong fit for a code-health
adapter when the analyzer already has a local checkout.

## Source and license

- Upstream: `https://github.com/github/git-sizer.git`
- Cloned at: `88eaa80df48db1b47291f3a43b084b8c79082339`
- License: MIT (`upstream/LICENSE.md`)
- Fixture: `spikes/_fixture/codex-external-audit-public-20260916`, commit
  `b83ea15980ed131e45318f34376e39a7bc45a022`

## Install and build

The exact source clone built successfully with Go `1.26.2`:

```text
go build -trimpath -o ../git-sizer.exe .
```

The build took `2.243 s` according to `runs/build.timing` and produced the
Windows executable used for the fixture run.

## Fixture run

The standard JSON probe was run from the fixture directory:

```text
git-sizer --json --json-version=2 --no-progress --verbose
```

It exited `0` in `0.408 s` (`runs/fixture.timing`) and wrote JSON v2 to
`runs/fixture.json`. The fixture contains seven refs and thirteen unique
commits. Selected values are:

```text
max blob size:             4,757 B
max checkout files:           10
max checkout size:         9,247 B
max checkout path depth:       2
max tree entries:             10
max history depth:            11
unique blobs / trees:     22 / 24
unique commits:               13
```

The report also includes concern ratios, object names, and descriptions such as
the ref containing the largest fixture blob. A non-Git directory exits `2`
with a clear object-resolution error; evidence is in
`runs/invalid_repo.stderr.log`.

## Integration boundary

The adapter should invoke the binary with an explicit JSON version and
`--no-progress`, parse the metric objects, and retain `objectDescription` when
present for explainability. No server, database, language runtime, or network
access is required at analysis time. The checkout/ref policy is part of the
result: git-sizer measures the refs and objects reachable from the repository
it scans.

## Runtime, complexity, and limitations

The scan is proportional to the reachable Git object graph and can consume
substantial time and memory on histories with many objects, large blobs, or
many refs. It reports repository-shape health rather than source-level bugs,
coverage, or semantic code quality. The fixture result is small and fast, but a
production adapter should impose process timeouts and preserve the tool's
non-zero exit/error payload.
