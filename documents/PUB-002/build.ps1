$ErrorActionPreference = "Stop"
$publicationRoot = $PSScriptRoot
Push-Location $publicationRoot
try {
    & uv run --script build.py
    if ($LASTEXITCODE -ne 0) { throw "Publication build failed." }
}
finally { Pop-Location }
Write-Output (Join-Path $publicationRoot "build/article.docx")
