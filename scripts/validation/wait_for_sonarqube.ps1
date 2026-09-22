[CmdletBinding()]
param(
    [string]$Url = "http://127.0.0.1:9000",
    [int]$TimeoutSeconds = 180,
    [int]$PollSeconds = 2
)

$ErrorActionPreference = "Stop"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$statusUrl = "$($Url.TrimEnd('/'))/api/system/status"

while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-RestMethod -Uri $statusUrl -Method Get -TimeoutSec 5
        if ($response.status -eq "UP") {
            Write-Output "status=UP url=$Url"
            exit 0
        }
        Write-Output "status=$($response.status)"
    } catch {
        Write-Output "status=unreachable"
    }
    Start-Sleep -Seconds $PollSeconds
}

throw "SonarQube did not reach UP within $TimeoutSeconds seconds: $statusUrl"
