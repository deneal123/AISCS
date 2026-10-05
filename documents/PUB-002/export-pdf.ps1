$ErrorActionPreference = 'Stop'
$publicationRoot = $PSScriptRoot
$publicationDocx = [IO.Path]::GetFullPath((Join-Path $publicationRoot 'build/article.docx'))
$publicationDoc = [IO.Path]::GetFullPath((Join-Path $publicationRoot 'build/article.doc'))
$publicationPdf = [IO.Path]::GetFullPath((Join-Path $publicationRoot 'build/article.pdf'))
$roundtripPdf = [IO.Path]::GetFullPath((Join-Path $publicationRoot 'build/article-doc.pdf'))
$publicationWord = New-Object -ComObject Word.Application
$publicationWord.Visible = $false
$publicationWord.DisplayAlerts = 0
function Get-PublicationText($document) {
    $text = $document.Content.Text
    # DOCX and DOC use different one-character inline-picture markers.
    # Remove only ranges identified by Word as pictures; preserve ordinary text.
    $ranges = @($document.InlineShapes | ForEach-Object { $_.Range } | Sort-Object Start -Descending)
    foreach ($range in $ranges) {
        $prefixLength = $document.Range($document.Content.Start, $range.Start).Text.Length
        $text = $text.Remove($prefixLength, $range.Text.Length)
    }
    return $text
}
try {
    $publicationDocument = $publicationWord.Documents.Open($publicationDocx, $false, $true)
    try {
        $publicationDocument.Repaginate()
        $originalText = Get-PublicationText $publicationDocument
        $originalPages = $publicationDocument.ComputeStatistics(2)
        $originalTables = $publicationDocument.Tables.Count
        $originalPictures = $publicationDocument.InlineShapes.Count
        $publicationDocument.ExportAsFixedFormat($publicationPdf, 17)
        $publicationDocument.RemovePersonalInformation = $true
        $publicationDocument.SaveAs2($publicationDoc, 0)
    }
    finally { $publicationDocument.Close(0) }
    $legacyDocument = $publicationWord.Documents.Open($publicationDoc, $false, $true)
    try {
        $legacyDocument.Repaginate()
        $legacyDocument.ExportAsFixedFormat($roundtripPdf, 17)
        $report = [ordered]@{
            same_text = $originalText -ceq (Get-PublicationText $legacyDocument)
            picture_marker_normalization = 'Only Word-identified inline-picture ranges excluded from text comparison'
            docx_pages = $originalPages
            doc_pages = $legacyDocument.ComputeStatistics(2)
            same_tables = $originalTables -eq $legacyDocument.Tables.Count
            same_pictures = $originalPictures -eq $legacyDocument.InlineShapes.Count
            normal_font = $legacyDocument.Styles.Item(-1).Font.Name
            normal_size = $legacyDocument.Styles.Item(-1).Font.Size
            normal_line_spacing_rule = $legacyDocument.Styles.Item(-1).ParagraphFormat.LineSpacingRule
            margins_points = @{
                top = $legacyDocument.PageSetup.TopMargin
                bottom = $legacyDocument.PageSetup.BottomMargin
                left = $legacyDocument.PageSetup.LeftMargin
                right = $legacyDocument.PageSetup.RightMargin
            }
        }
        $json = ($report | ConvertTo-Json -Depth 4) -replace "`r`n", "`n"
        [IO.File]::WriteAllText((Join-Path $publicationRoot 'build/doc-roundtrip.json'), $json + "`n", [Text.UTF8Encoding]::new($false))
        if (-not $report.same_text -or -not $report.same_tables -or -not $report.same_pictures -or $report.docx_pages -ne $report.doc_pages) { throw 'Word 97-2003 roundtrip mismatch.' }
    }
    finally { $legacyDocument.Close(0) }
}
finally { $publicationWord.Quit() }
Write-Output $publicationPdf
