[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$output = Join-Path $PSScriptRoot "build/latex"
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $PSScriptRoot
try {
    1..2 | ForEach-Object {
        & xelatex -interaction=nonstopmode -halt-on-error -synctex=1 "-output-directory=$output" -jobname=article-latex main.tex
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed on pass $_." }
    }
}
finally { Pop-Location }
Write-Output (Join-Path $output "article-latex.pdf")
