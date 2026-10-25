[CmdletBinding()]
param([switch]$SkipBuild, [switch]$SkipMcp)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $checkOptions = @()
    if ($SkipBuild) { $checkOptions += "--skip-build" }
    if ($SkipMcp) { $checkOptions += "--skip-mcp" }
    uv run --frozen --extra dev python scripts/check.py @checkOptions
    if ($LASTEXITCODE -ne 0) { throw "Project checks failed ($LASTEXITCODE)." }
}
finally { Pop-Location }
