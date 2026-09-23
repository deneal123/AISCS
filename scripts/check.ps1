$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    uv run --extra dev --frozen researchctl validate
    uv run --extra dev --frozen ruff check service tests migrations scripts
    uv run --extra dev --frozen pytest -q
}
finally {
    Pop-Location
}
