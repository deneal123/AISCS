[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$serverName = "aspa-research"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$codex = (Get-Command codex -ErrorAction Stop).Source
$null = Get-Command uv.exe -ErrorAction Stop
$uv = "uv.exe"
$desiredArgs = @("run", "--directory", $projectDir, "--frozen", "research-mcp")

function Get-ConfiguredServer {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $codex mcp get $serverName --json 2>$null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        return $null
    }
    return ($output | ConvertFrom-Json)
}

$existing = Get-ConfiguredServer

if ($Remove) {
    if ($null -eq $existing) {
        Write-Output "$serverName is not configured."
        exit 0
    }
    & $codex mcp remove $serverName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove $serverName."
    }
    Write-Output "Removed $serverName."
    exit 0
}

$sameCommand = $null -ne $existing -and $existing.transport.command -eq $uv
$sameArgs = $null -ne $existing -and (
    ($existing.transport.args | ConvertTo-Json -Compress) -eq ($desiredArgs | ConvertTo-Json -Compress)
)

if ($sameCommand -and $sameArgs) {
    Write-Output "$serverName is already configured with the expected command."
    exit 0
}

if ($null -ne $existing -and -not $Force) {
    throw "$serverName has a conflicting configuration. Re-run with -Force to replace it."
}

if ($null -ne $existing) {
    & $codex mcp remove $serverName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove the conflicting $serverName configuration."
    }
}

& $codex mcp add $serverName -- $uv @desiredArgs
if ($LASTEXITCODE -ne 0) {
    throw "Failed to add $serverName."
}

Write-Output "Configured $serverName. Restart Codex or open a new session to load it."
