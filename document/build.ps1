[CmdletBinding()]
param([ValidateSet("draft", "release")][string]$Profile = "draft")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$output = Join-Path $root "build"
New-Item -ItemType Directory -Force -Path $output | Out-Null

function Invoke-XeLaTeX([string]$InputValue, [switch]$Draft) {
    $arguments = @("-interaction=nonstopmode", "-halt-on-error", "-output-directory=$output")
    if ($Draft) { $arguments += "-jobname=dissertation" }
    $arguments += $InputValue
    & xelatex @arguments
    if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed." }
}

Push-Location $root
try {
    if ($Profile -eq "draft") {
        $inputValue = '\def\ASPADraft{1}\input{dissertation.tex}'
        Invoke-XeLaTeX $inputValue -Draft
        Invoke-XeLaTeX $inputValue -Draft
    }
    else {
        Invoke-XeLaTeX "dissertation.tex"
        # Perl on Windows may reject the inherited locale even when Biber succeeds.
        $previousLang = $env:LANG
        $previousLocale = $env:LC_ALL
        try {
            $env:LANG = "C"
            $env:LC_ALL = "C"
            & biber "--output-directory=$output" (Join-Path $output "dissertation")
            if ($LASTEXITCODE -ne 0) { throw "Biber failed." }
        }
        finally {
            $env:LANG = $previousLang
            $env:LC_ALL = $previousLocale
        }
        Invoke-XeLaTeX "dissertation.tex"
        Invoke-XeLaTeX "dissertation.tex"
    }
}
finally { Pop-Location }
Copy-Item -LiteralPath (Join-Path $output "dissertation.pdf") -Destination (Join-Path $root "dissertation.pdf") -Force
Write-Output (Join-Path $output "dissertation.pdf")
