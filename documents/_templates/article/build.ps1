$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$output = Join-Path $root "build"
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $root
try {
    1..2 | ForEach-Object {
        & xelatex -interaction=nonstopmode -halt-on-error "-output-directory=$output" main.tex
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed on pass $_." }
    }
}
finally { Pop-Location }
Write-Output (Join-Path $output "main.pdf")
