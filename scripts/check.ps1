$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    uv run --extra dev --frozen pubctl validate
    uv run --extra dev --frozen ruff check service tests scripts/mcp-smoke.py
    uv run --extra dev --frozen pytest -q
    uv run --frozen pubctl build PUB-TEMPLATE-001 --profile draft
    uv run --frozen python scripts/mcp-smoke.py
}
finally { Pop-Location }
