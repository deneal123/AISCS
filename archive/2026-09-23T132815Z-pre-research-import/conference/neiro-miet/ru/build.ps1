param(
    [switch]$RefreshSearch
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($RefreshSearch) {
    Push-Location (Join-Path $scriptRoot 'review')
    try {
        uv run run_review.py
        if ($LASTEXITCODE -ne 0) { throw "run_review.py failed with exit code $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
}

Push-Location $scriptRoot
try {
    uv run build_article.py
    if ($LASTEXITCODE -ne 0) { throw "build_article.py failed with exit code $LASTEXITCODE" }

    $docx = Join-Path $scriptRoot 'article.docx'
    $tempDir = Join-Path $env:TEMP 'aspa-neiro-miet-word-check'
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $localDocx = Join-Path $tempDir 'article.docx'
    Copy-Item -LiteralPath $docx -Destination $localDocx -Force
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {
        $document = $word.Documents.Open($localDocx, $false, $true)
        try {
            $pages = $document.ComputeStatistics(2)
            $words = $document.ComputeStatistics(0)
            $characters = $document.ComputeStatistics(3)
            $lastRange = $document.Content.Duplicate
            $lastRange.Collapse(0)
            $null = $lastRange.MoveStart(1, -1)
            $lastY = [double]$lastRange.Information(6)
            $usableBottom = [double]$document.PageSetup.PageHeight - [double]$document.PageSetup.BottomMargin
            $bottomReservePt = $usableBottom - $lastY
            Write-Host "Word pages: $pages"
            if ($pages -ne 8) { throw "Word page count is $pages; expected exactly 8" }
            if ($bottomReservePt -lt 28.35) { throw "Last-page reserve is $bottomReservePt pt; expected at least 28.35 pt (1 cm)" }
            $wordStats = [ordered]@{
                docx_sha256 = (Get-FileHash -LiteralPath $docx -Algorithm SHA256).Hash
                word_pages = $pages
                word_words = $words
                word_characters = $characters
                last_page_bottom_reserve_pt = [math]::Round($bottomReservePt, 2)
            }
            $wordStats | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $scriptRoot 'validation_word_stats.json') -Encoding utf8
        }
        finally {
            $document.Close(0)
        }
    }
    finally {
        $word.Quit()
    }

    $finalPdf = Join-Path $scriptRoot 'article.pdf'
    $localPdf = Join-Path $tempDir 'article.pdf'
    Remove-Item -LiteralPath $localPdf -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $finalPdf -Force -ErrorAction SilentlyContinue
    $exportHelper = Join-Path $scriptRoot 'export_word_pdf.ps1'
    $exportProcess = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $exportHelper,
        '-InputDocx', $localDocx, '-OutputPdf', $localPdf
    )
    $wordExportOk = $exportProcess.WaitForExit(120000)
    if (-not $wordExportOk) {
        Stop-Process -Id $exportProcess.Id -Force -ErrorAction SilentlyContinue
    }
    elseif ($exportProcess.ExitCode -eq 0 -and (Test-Path -LiteralPath $localPdf)) {
        Copy-Item -LiteralPath $localPdf -Destination $finalPdf -Force
    }
    else {
        $wordExportOk = $false
    }

    uv run render_pdf.py
    if ($LASTEXITCODE -ne 0) { throw "render_pdf.py failed with exit code $LASTEXITCODE" }
    if (-not $wordExportOk) {
        throw "Microsoft Word PDF export did not complete; article.preview.pdf was created, article.pdf is intentionally absent"
    }

    $releaseManifest = [ordered]@{
        release_tag = 'min-2026-review-v1.0.0'
        release_url = 'https://github.com/deneal123/AISCS/releases/tag/min-2026-review-v1.0.0'
        git_commit = 'eea2091e0629600545043e218db43ef86e6eec96'
        public_appendix_manifest_sha256 = '030BC4EC572B51479F77EEC7B2A80CDD3568B1163F9BD77B0002FF3C5DBC2485'
        article_docx_sha256 = (Get-FileHash -LiteralPath $docx -Algorithm SHA256).Hash
        article_pdf_sha256 = (Get-FileHash -LiteralPath $finalPdf -Algorithm SHA256).Hash
        article_preview_pdf_sha256 = (Get-FileHash -LiteralPath (Join-Path $scriptRoot 'article.preview.pdf') -Algorithm SHA256).Hash
    }
    $releaseManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $scriptRoot 'release_manifest.json') -Encoding utf8

    uv run validate_artifacts.py
    if ($LASTEXITCODE -ne 0) { throw "validate_artifacts.py failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
