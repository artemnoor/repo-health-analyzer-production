[CmdletBinding()]
param(
    [string]$Name = "repo-health-sonarqube",
    [string]$Image = $(if ($env:SONARQUBE_IMAGE) { $env:SONARQUBE_IMAGE } else { "sonarqube:community" }),
    [int]$Port = 9000,
    [switch]$Pull
)

$ErrorActionPreference = "Stop"

docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker daemon is unavailable. Run the diagnostics in docs/validation/docker-sonarqube-setup.md first."
}

$existing = docker container inspect $Name 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
if ($existing) {
    $state = $existing[0].State.Status
    if ($state -eq "running") {
        Write-Output "container=$Name state=running image=$Image"
        exit 0
    }
    docker start $Name | Out-Null
    Write-Output "container=$Name state=started image=$Image"
    exit 0
}

if ($Pull) {
    docker pull $Image
    if ($LASTEXITCODE -ne 0) { throw "Could not pull official SonarQube image: $Image" }
}

docker run --detach --name $Name `
    --publish "127.0.0.1:${Port}:9000" `
    --env "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true" `
    $Image | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not start SonarQube container $Name" }
Write-Output "container=$Name state=started image=$Image endpoint=http://127.0.0.1:$Port"
