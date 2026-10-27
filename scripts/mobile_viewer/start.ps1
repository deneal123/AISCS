param([switch]$CheckOnly)
. (Join-Path $PSScriptRoot 'environment.ps1')
$viewer = Get-MobileViewerPaths
$viewerLaunchLock = [System.IO.File]::Open((Join-Path $viewer.Base 'launch.lock'),
  [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
foreach ($viewerFile in @($viewer.Node,$viewer.CacheNode,$viewer.Entry,$viewer.Adb,$viewer.Config,$viewer.Receipt,$viewer.Preload)) {
  if (-not (Test-Path -LiteralPath $viewerFile -PathType Leaf)) { throw 'Сначала выполните scripts/mobile_viewer/install.ps1.' }
}
$viewerReceipt = Get-Content -Raw -Encoding UTF8 $viewer.Receipt | ConvertFrom-Json
foreach ($viewerCheck in @(@{File=$viewer.Node;Hash=$viewerReceipt.node_sha256},
  @{File=$viewer.CacheNode;Hash=$viewerReceipt.cache_node_sha256},
  @{File=$viewer.Entry;Hash=$viewerReceipt.entry_sha256},@{File=$viewer.Adb;Hash=$viewerReceipt.adb_sha256})) {
  if ((Get-FileHash -LiteralPath $viewerCheck.File).Hash -ne $viewerCheck.Hash) { throw 'Файл установки изменён. Запуск запрещён.' }
}
if (Test-Path -LiteralPath (Join-Path $viewer.Base 'runtime/Update.exe')) { throw 'Обновление просмотрщика не отключено. Повторите install.ps1.' }
$viewerConfig = Get-Content -Raw -Encoding UTF8 $viewer.Config | ConvertFrom-Json
if ($viewerConfig.webPort -ne 8099 -or $viewerConfig.autoUpdate -ne $false -or
  $viewerConfig.adbPath -ne $viewer.Adb -or $viewerConfig.dependenciesPath -ne $viewer.Dependencies) {
  throw 'Конфигурация выходит за пределы согласованного локального запуска.'
}
foreach ($viewerPort in @(8099,5038)) {
  $viewerListener = @(Get-NetTCPConnection -LocalPort $viewerPort -State Listen -ErrorAction SilentlyContinue)
  if ($viewerListener.Count -gt 0) { throw "Порт $viewerPort занят. Существующий процесс не останавливаю." }
}
if ($CheckOnly) { Write-Output 'Preflight пройден; сервер, ADB и эмулятор не запускались.'; return }

$viewerEnvironment = @{
  DATA_ROOT=$viewer.Data; WS_SCRCPY_CONFIG=$viewer.Config
  GPTHUB_VIEWER_ADB=$viewer.Adb; GPTHUB_VIEWER_NODE=$viewer.CacheNode; WS_SCRCPY_NO_BROWSER='1'
  ADB_SERVER_SOCKET='tcp:localhost:5038'; ANDROID_ADB_SERVER_PORT='5038'
  ADB_MDNS_AUTO_CONNECT='0'; ADB_MDNS='0'
}
$viewerPreviousEnvironment = @{}
$viewerStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$viewerStdout = Join-Path $viewer.Logs "$viewerStamp.stdout.log"
$viewerStderr = Join-Path $viewer.Logs "$viewerStamp.stderr.log"
try {
  foreach ($viewerKey in $viewerEnvironment.Keys) {
    $viewerPreviousEnvironment[$viewerKey] = [Environment]::GetEnvironmentVariable($viewerKey, 'Process')
    [Environment]::SetEnvironmentVariable($viewerKey, $viewerEnvironment[$viewerKey], 'Process')
  }
  $viewerProcess = Start-Process -FilePath $viewer.Node -ArgumentList @('--require',('"{0}"' -f $viewer.Preload),('"{0}"' -f $viewer.Entry)) -WorkingDirectory $viewer.Current -WindowStyle Hidden -RedirectStandardOutput $viewerStdout -RedirectStandardError $viewerStderr -PassThru
} finally {
  foreach ($viewerKey in $viewerPreviousEnvironment.Keys) {
    [Environment]::SetEnvironmentVariable($viewerKey, $viewerPreviousEnvironment[$viewerKey], 'Process')
  }
}
Write-MobileViewerJson ([ordered]@{ process_id=$viewerProcess.Id; node=$viewer.Node; entry=$viewer.Entry
  preload=$viewer.Preload; stdout=$viewerStdout; stderr=$viewerStderr; started_utc=[DateTime]::UtcNow.ToString('o') }) $viewer.Process
for ($viewerAttempt=0; $viewerAttempt -lt 60; $viewerAttempt++) {
  if ($viewerProcess.HasExited) { throw "Просмотрщик завершился; диагностика: $viewerStderr" }
  $viewerListening = @(Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue)
  if ($viewerListening.Count -gt 0) {
    if (@($viewerListening | Where-Object { $_.LocalAddress -ne '127.0.0.1' -or $_.OwningProcess -ne $viewerProcess.Id }).Count -gt 0) {
      throw 'Неожиданный владелец или адрес порта. Готовность не подтверждена.'
    }
    Write-Output 'Просмотрщик: http://localhost:8099 (только loopback). Эмулятор не запускался.'
    return
  }
  Start-Sleep -Milliseconds 250
}
throw "HTTP ещё не готов. Повторно процесс не запускаю; диагностика: $viewerStderr"
} finally { $viewerLaunchLock.Dispose() }
