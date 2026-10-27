Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-MobileViewerPaths {
  $viewerBase = Join-Path $env:LOCALAPPDATA 'Android/GPTHubSetup/viewer/ws-scrcpy-web-v0.5.10'
  $viewerCurrent = Join-Path $viewerBase 'runtime/current'
  $viewerData = Join-Path $viewerBase 'data'
  return [pscustomobject]@{
    Base = $viewerBase
    Archive = Join-Path $viewerBase 'download/WsScrcpyWeb-stable-Portable.zip'
    Current = $viewerCurrent
    Data = $viewerData
    Node = Join-Path $viewerCurrent 'seed/node/node.exe'
    CacheNode = Join-Path $viewerData 'dependencies/node/node.exe'
    DisabledUpdater = Join-Path $viewerBase 'download/disabled-updater/Update.exe'
    Entry = Join-Path $viewerCurrent 'dist/index.js'
    Dependencies = Join-Path $viewerData 'dependencies'
    Adb = Join-Path $viewerData 'dependencies/adb/adb.exe'
    Config = Join-Path $viewerData 'config.json'
    Receipt = Join-Path $viewerBase 'installation.json'
    Process = Join-Path $viewerBase 'process.json'
    Logs = Join-Path $viewerBase 'logs'
    Preload = Join-Path $PSScriptRoot 'preload.cjs'
  }
}

function Write-MobileViewerJson($Value, [string]$Destination) {
  $viewerJson = $Value | ConvertTo-Json -Depth 8
  [System.IO.File]::WriteAllText($Destination, $viewerJson, (New-Object System.Text.UTF8Encoding($false)))
}

function Assert-MobileViewerArchive([string]$Archive) {
  if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne
    '61D8DC2D96CC44671E6CA384F539AE9713A1CD1A9329FD8EBB37919AEE0A6506') {
    throw 'Контрольная сумма архива просмотрщика не совпала. Запуск запрещён.'
  }
}
