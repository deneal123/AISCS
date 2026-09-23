param(
    [Parameter(Mandatory = $true)][string]$InputDocx,
    [Parameter(Mandatory = $true)][string]$OutputPdf
)

$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $document = $word.Documents.Open($InputDocx, $false, $true)
    try {
        # wdExportFormatPDF = 17; export from the local copy avoids network-drive locks.
        $document.ExportAsFixedFormat($OutputPdf, 17)
    }
    finally {
        $document.Close(0)
    }
}
finally {
    $word.Quit()
}

