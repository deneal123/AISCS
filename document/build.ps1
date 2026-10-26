[CmdletBinding()]
param(
    # presentation — доклад к защите (PRES-001), progress — еженедельный отчёт (PRES-002).
    [ValidateSet("presentation", "progress")]
    [string]$Deck = "presentation"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$output = Join-Path $root "build"
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $root
try {
    1..2 | ForEach-Object {
        & xelatex -interaction=nonstopmode -halt-on-error "-output-directory=$output" "$Deck.tex"
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed on pass $_." }
    }
}
finally { Pop-Location }
Copy-Item -LiteralPath (Join-Path $output "$Deck.pdf") -Destination (Join-Path $root "$Deck.pdf") -Force
Write-Output (Join-Path $output "$Deck.pdf")
