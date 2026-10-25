[CmdletBinding()]
param([switch]$SkipMcp)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $checkOptions = @()
    if ($SkipMcp) { $checkOptions += "--skip-mcp" }
    uv run --frozen --extra dev python scripts/check.py @checkOptions
    if ($LASTEXITCODE -ne 0) { throw "Research checks failed ($LASTEXITCODE)." }
}
finally { Pop-Location }
