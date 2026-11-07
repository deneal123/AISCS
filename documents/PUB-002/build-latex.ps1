[CmdletBinding()]
param([switch]$Tools)

$ErrorActionPreference = "Stop"
$output = Join-Path $PSScriptRoot $(if ($Tools) { "build/tools/latex" } else { "build/latex" })
$source = if ($Tools) { "build/tools/main.tex" } else { "main.tex" }
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $PSScriptRoot
try {
    1..2 | ForEach-Object {
        & xelatex -interaction=nonstopmode -halt-on-error -synctex=1 "-output-directory=$output" -jobname=article-latex $source
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed on pass $_." }
    }
}
finally { Pop-Location }
Write-Output (Join-Path $output "article-latex.pdf")
