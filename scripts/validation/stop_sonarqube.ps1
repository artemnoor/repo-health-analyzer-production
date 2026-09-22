[CmdletBinding()]
param(
    [string]$Name = "repo-health-sonarqube"
)

$ErrorActionPreference = "Stop"
$existing = docker container inspect $Name 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Output "container=$Name state=absent"
    exit 0
}

docker stop $Name | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not stop explicitly named container $Name" }
docker rm $Name | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not remove explicitly named container $Name" }
Write-Output "container=$Name state=removed"
