# Local-tool validation setup

This setup is for the validation lab only. It does not add Vale, git-sizer,
SonarQube, scanner binaries, or upstream source to the production package.

## Pinned tools

The versions and SHA-256 values are in
[`scripts/validation/tool-versions.json`](../../scripts/validation/tool-versions.json).
The bootstrap downloads the official Vale and git-sizer Windows archives and
the official SonarScanner CLI archive into an ignored directory.

```powershell
$toolRoot = 'C:\rhvl-tools-20260921'
pwsh -File scripts/validation/bootstrap_local_tools.ps1 -ToolRoot $toolRoot
$env:VALE_PATH = "$toolRoot\bin\vale.exe"
$env:GIT_SIZER_PATH = "$toolRoot\bin\git-sizer.exe"
$env:SONAR_SCANNER_PATH = "$toolRoot\bin\sonar-scanner-8.1.0.6389-windows-x64\bin\sonar-scanner.bat"
```

If an upstream archive is blocked by the environment, do not substitute an
unverified mirror. To verify only the downloadable local tools while recording
that limitation, use `-SkipSonarScanner`; otherwise use the official Docker
scanner image after Docker is available.

## SonarQube

Docker Desktop must be running and `docker info` must succeed. SonarQube needs a
local server because the production collector reads its REST measures; it does
not run a local static scanner itself.

```powershell
docker info
docker pull sonarqube:community
docker run --rm --name repo-health-sonarqube `
  -p 9000:9000 `
  -e SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true `
  sonarqube:community
```

The validation orchestration keeps the generated Sonar token in the current
process environment only. It never enters contracts, reports, logs, or SQLite.
Each matrix repository uses a Sonar-valid project key `github.<slug>`; the
public GitHub URL and immutable HEAD SHA remain the audit identity. SonarQube
is deliberately opt-in because GitHub-only validation must not accidentally
send public repository identifiers to an arbitrary server.

## Full local-tool matrix

After the SonarQube environment is ready, run the same manifest as the baseline:

```powershell
$env:SONAR_TOKEN = '<short-lived local SonarQube token>'
uv run python scripts/validation/run_validation_matrix.py `
  --output-root artifacts/validation/<timestamp>-local-tools `
  --checkout-root $env:TEMP\repo-health-validation\<timestamp>-local-tools `
  --enable-sonarqube `
  --sonar-url http://127.0.0.1:9000 `
  --report-path docs/validation/local-tool-validation-after.md
```

The token line is illustrative only: create a short-lived local token and do
not paste its value into the repository, command history, or report.

The actual command used for a run and the resulting tool/server versions are
stored in the timestamped ignored artifact root. The previous baseline at
`artifacts/validation/20260921T193407Z-420d811d` is never overwritten.

## Cleanup

Stop only the explicitly labelled validation container and remove the external
tool root after preserving the report:

```powershell
docker rm -f repo-health-sonarqube
Remove-Item -LiteralPath $toolRoot -Recurse -Force
```

The final report must state when Docker or any external binary was unavailable;
missing tools remain `unavailable/partial/inconclusive`, never score zero.
