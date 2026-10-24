$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    uv run --extra dev --frozen pubctl validate
    if ($LASTEXITCODE -ne 0) { throw "Registry validation failed ($LASTEXITCODE)." }
    uv run --extra dev --frozen ruff check service tests scripts/mcp-smoke.py
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed ($LASTEXITCODE)." }
    uv run --extra dev --frozen pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed ($LASTEXITCODE)." }
    uv run --frozen pubctl build PUB-TEMPLATE-001 --profile draft
    if ($LASTEXITCODE -ne 0) { throw "Draft build failed ($LASTEXITCODE)." }
    uv run --frozen python scripts/mcp-smoke.py
    if ($LASTEXITCODE -ne 0) { throw "MCP smoke failed ($LASTEXITCODE)." }
}
finally { Pop-Location }
