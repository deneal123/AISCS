param(
    [string]$WorkDirectory = "",
    [switch]$SkipPreview
)
$ErrorActionPreference = 'Stop'
$sourceDirectory = $PSScriptRoot
$superproject = [IO.Path]::GetFullPath((Join-Path $sourceDirectory '../../../..'))
if (-not $WorkDirectory) {
    $WorkDirectory = Join-Path $superproject 'research/.work/min2026-poster-20261020/refined-build'
}
$WorkDirectory = [IO.Path]::GetFullPath($WorkDirectory)
New-Item -ItemType Directory -Force -Path $WorkDirectory | Out-Null
$temporaryDirectory = Join-Path $WorkDirectory 'tmp'
New-Item -ItemType Directory -Force -Path $temporaryDirectory | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
Push-Location $sourceDirectory
try {
    $env:TEMP = $temporaryDirectory
    $env:TMP = $temporaryDirectory
    $engineOptions = @()
    if ((Get-Command xelatex).Source -match 'MiKTeX') {
        $engineOptions += '--disable-installer'
    }
    & xelatex @engineOptions -interaction=nonstopmode -halt-on-error -file-line-error `
        "-output-directory=$WorkDirectory" poster.tex
    if ($LASTEXITCODE -ne 0) { throw 'XeLaTeX failed; the previous poster_A1_refined.pdf was preserved.' }
    & xelatex @engineOptions -interaction=nonstopmode -halt-on-error -file-line-error `
        "-output-directory=$WorkDirectory" poster.tex
    if ($LASTEXITCODE -ne 0) { throw 'XeLaTeX second pass failed; the previous PDF was preserved.' }
    $log = Get-Content -LiteralPath (Join-Path $WorkDirectory 'poster.log') -Raw
    if ($log -match 'Overfull \\[hv]box|Missing character:') {
        throw 'An overflowing TeX box or missing glyph must be corrected before export.'
    }
    $pdf = Join-Path $WorkDirectory 'poster.pdf'
    $info = (& pdfinfo $pdf) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $info -notmatch 'Pages:\s+1\b') {
        throw 'Expected a valid single-page poster PDF.'
    }
    if ($info -notmatch 'Page size:\s+([\d.]+) x ([\d.]+) pts') {
        throw 'Cannot verify the PDF page dimensions.'
    }
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $widthMm = [double]::Parse($Matches[1], $culture) * 25.4 / 72
    $heightMm = [double]::Parse($Matches[2], $culture) * 25.4 / 72
    if ([Math]::Abs($widthMm - 594) -gt 0.02 -or [Math]::Abs($heightMm - 841) -gt 0.02) {
        throw 'The PDF must be exactly A1 (594 x 841 mm).'
    }
    if (-not $SkipPreview) {
        & pdftoppm -f 1 -singlefile -scale-to 2400 -png $pdf (Join-Path $WorkDirectory 'poster')
        if ($LASTEXITCODE -ne 0) { throw 'PNG preview generation failed.' }
    }
    Copy-Item -LiteralPath $pdf -Destination (Join-Path $sourceDirectory 'poster_A1_refined.pdf') -Force
    # Keep an existing editor preview in sync, without creating another default output.
    $editorPreview = Join-Path $sourceDirectory 'poster.pdf'
    if (Test-Path -LiteralPath $editorPreview) {
        Copy-Item -LiteralPath $pdf -Destination $editorPreview -Force
    }
    if (-not $SkipPreview) {
        Copy-Item -LiteralPath (Join-Path $WorkDirectory 'poster.png') `
            -Destination (Join-Path $sourceDirectory 'poster_A1_refined.png') -Force
    }
    Write-Output "Poster: $(Join-Path $sourceDirectory 'poster_A1_refined.pdf')"
} finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    Pop-Location
}
