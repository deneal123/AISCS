$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    uv run --frozen research-sidecar
}
finally {
    Pop-Location
}
