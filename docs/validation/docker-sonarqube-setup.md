# Docker and SonarQube validation setup

This document covers the isolated validation container only. Production code
does not require Docker and never shells out to Docker.

## Incident observed on 2026-09-22

Docker Desktop was installed and the `desktop-linux` context was selected, but
the daemon was not usable:

- `docker info` could not open the `dockerDesktopLinuxEngine` pipe;
- Docker Desktop reported `com.docker.build` exit status 1;
- the VM log reported `dockerd failed to start: starting rpcbind: signal: killed`;
- the retry reported `starting rpcbind: context canceled`;
- low free disk space was observed on the Windows system volume.

No Docker factory reset, volume deletion, image prune, or broad container
cleanup was performed. A native SonarQube 26.9.0.129388 installation was used
as a non-destructive fallback and reached `GET /api/system/status` → `UP`.

After a non-destructive `docker desktop start`, three repeated `docker info`
probes over the following interval all failed with the same missing
`dockerDesktopLinuxEngine` pipe. `com.docker.service` remained `Stopped`.

## Safe diagnosis

Run these read-only checks in PowerShell:

```powershell
docker desktop status
docker context ls
docker version
docker info
wsl --status
wsl --version
wsl --list --verbose
Get-Service com.docker.service
Get-Process 'Docker Desktop','com.docker.backend','com.docker.service' -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 9000 -ErrorAction SilentlyContinue
Get-PSDrive C,D | Select-Object Name,Free,Used
```

Inspect Docker Desktop logs from the user's local Docker log directory. Do
not paste tokens or full diagnostic bundles into the repository.

## Minimal recovery sequence

The following does not delete Docker data:

```powershell
docker desktop start
Start-Sleep -Seconds 10
docker info
wsl --status
```

If Docker Desktop is still unhealthy, close Docker Desktop normally, then use
`wsl --shutdown` and start Docker Desktop again. Restarting
`com.docker.service` may require an elevated PowerShell window and should be
done only when Docker Desktop is closed:

```powershell
Get-Service com.docker.service
Restart-Service com.docker.service
docker desktop start
docker info
```

Do not run `docker system prune`, delete `%LOCALAPPDATA%\Docker`, reset the
factory, or remove volumes as an automatic troubleshooting step.

## Reproducible SonarQube container

Use the official SonarSource image only. For reproducibility, set
`SONARQUBE_IMAGE` to an approved immutable tag or digest in the local
environment; no image is vendored into this repository.

```powershell
$env:SONARQUBE_IMAGE = 'sonarqube:community'
pwsh -File scripts/validation/start_sonarqube.ps1 -Pull
pwsh -File scripts/validation/wait_for_sonarqube.ps1
Invoke-RestMethod http://127.0.0.1:9000/api/system/status
```

The start script binds only to `127.0.0.1`, reuses the explicitly named
`repo-health-sonarqube` container, and never removes unrelated resources. The
wait script refuses to proceed until the status is `UP`.

Stop only that validation container when finished:

```powershell
pwsh -File scripts/validation/stop_sonarqube.ps1
```

## Scanner and collector proof

After readiness, use the official SonarScanner distribution or the official
scanner image. Keep the short-lived Sonar token in the current process only:

```powershell
$env:SONAR_URL = 'http://127.0.0.1:9000'
$env:SONAR_TOKEN = '<short-lived local token>'
& $env:SONAR_SCANNER_PATH `
  '-Dsonar.projectKey=repo-health-validation' `
  '-Dsonar.sources=.' `
  "-Dsonar.host.url=$env:SONAR_URL" `
  "-Dsonar.token=$env:SONAR_TOKEN"
uv run python scripts/verify_production_composition.py --live `
  --checkout-path . `
  --repository-id repo-health-validation `
  --canonical-uri https://sourcecraft.dev/validation/repo-health-validation
```

Revoke the token after the run. The token must never enter Git, facts,
SQLite, reports, or logs.

## Known limitations

- Docker Desktop can remain unavailable when its VM fails during `rpcbind`
  startup or when disk pressure prevents the VM from booting.
- Vale and git-sizer are optional external binaries; the backend reports them
  as unavailable/partial instead of inventing measurements.
- Native SonarQube is an acceptable local validation fallback when Docker is
  unavailable, but the Docker path should be re-tested before relying on a
  containerized deployment.
