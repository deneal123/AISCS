$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    uv run --extra dev --frozen researchctl validate
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv run --extra dev --frozen ruff check service tests migrations scripts
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv run --extra dev --frozen pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
