[CmdletBinding()]
param([switch]$Force, [switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "aspa-publications"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desired = @("run", "--directory", $root, "--frozen", "publications-mcp")
$current = $null
try { $current = (& codex mcp get $name --json 2>$null | ConvertFrom-Json) } catch {}
if ($Remove) { if ($current) { & codex mcp remove $name }; exit $LASTEXITCODE }
$same = $current -and $current.transport.command -eq "uv.exe" -and (($current.transport.args | ConvertTo-Json -Compress) -eq ($desired | ConvertTo-Json -Compress))
if ($same) { Write-Output "$name is already configured."; exit 0 }
if ($current -and -not $Force) { throw "$name conflicts; use -Force." }
if ($current) { & codex mcp remove $name }
& codex mcp add $name -- uv.exe @desired
if ($LASTEXITCODE -ne 0) { throw "Failed to configure $name." }
