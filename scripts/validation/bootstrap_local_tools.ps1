[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ToolRoot,
    [switch]$Force,
    [switch]$SkipSonarScanner
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$versionsPath = Join-Path $scriptRoot "tool-versions.json"
$versions = Get-Content -Raw -LiteralPath $versionsPath | ConvertFrom-Json
$root = [System.IO.Path]::GetFullPath($ToolRoot)
$downloadRoot = Join-Path $root "downloads"
$binRoot = Join-Path $root "bin"
New-Item -ItemType Directory -Force -Path $root, $downloadRoot, $binRoot | Out-Null

function Get-ToolProperty([object]$Tool, [string]$Name) {
    return $Tool.PSObject.Properties[$Name].Value
}

function Install-ArchiveTool([string]$Name, [object]$Tool) {
    $archiveName = [System.IO.Path]::GetFileName((Get-ToolProperty $Tool "url"))
    $archivePath = Join-Path $downloadRoot $archiveName
    $executable = Join-Path $binRoot (Get-ToolProperty $Tool "executable")
    if (-not $Force -and (Test-Path -LiteralPath $executable)) {
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath -ErrorAction SilentlyContinue).Hash
        if ($actualHash -and $actualHash.ToLowerInvariant() -eq (Get-ToolProperty $Tool "sha256")) {
            Write-Output ("{0}: reusing pinned archive and executable" -f $Name)
            return $executable
        }
    }
    if ($Force -or -not (Test-Path -LiteralPath $archivePath)) {
        Invoke-WebRequest -Uri (Get-ToolProperty $Tool "url") -OutFile $archivePath -UseBasicParsing
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualHash -ne (Get-ToolProperty $Tool "sha256")) {
        throw "$Name archive SHA-256 mismatch: expected $((Get-ToolProperty $Tool 'sha256')), got $actualHash"
    }
    Expand-Archive -Force -LiteralPath $archivePath -DestinationPath $binRoot
    if (-not (Test-Path -LiteralPath $executable)) {
        throw "$Name executable was not found after extraction: $executable"
    }
    return $executable
}

$installed = [ordered]@{}
$installed["vale"] = Install-ArchiveTool "vale" $versions.vale
$installed["git-sizer"] = Install-ArchiveTool "git-sizer" $versions.'git-sizer'
$scanner = $null
if (-not $SkipSonarScanner) {
    $scanner = Install-ArchiveTool "sonar-scanner" $versions.'sonar-scanner'
}

$versionOutput = [ordered]@{}
$versionOutput["vale"] = (& $installed["vale"] --version | Select-Object -First 1).Trim()
$versionOutput["git-sizer"] = (& $installed["git-sizer"] --version | Select-Object -First 1).Trim()
$versionOutput["sonar-scanner"] = if ($scanner) { (& $scanner --version 2>&1 | Select-Object -First 2 | Out-String).Trim() } else { "skipped: official archive unavailable or Docker scanner selected" }
$manifest = [ordered]@{
    tool_root = $root
    versions_file = [System.IO.Path]::GetFullPath($versionsPath)
    executables = $installed
    versions = $versionOutput
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
}
$manifestPath = Join-Path $root "tool-manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$manifest | ConvertTo-Json -Depth 6
