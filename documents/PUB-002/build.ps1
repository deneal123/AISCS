[CmdletBinding()]
param([switch]$Tools)
$ErrorActionPreference = "Stop"
$publicationRoot = $PSScriptRoot
Push-Location $publicationRoot
try {
    if ($Tools) { & uv run --quiet --script build.py --tools }
    else { & uv run --quiet --script build.py }
    if ($LASTEXITCODE -ne 0) { throw "Publication build failed." }
}
finally { Pop-Location }
if ($Tools) { Write-Output (Join-Path $publicationRoot "build/tools/article.docx") }
else { Write-Output (Join-Path $publicationRoot "build/article.docx") }
