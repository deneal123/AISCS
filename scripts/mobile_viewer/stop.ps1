. (Join-Path $PSScriptRoot 'environment.ps1')
$viewer = Get-MobileViewerPaths
if (-not (Test-Path -LiteralPath $viewer.Process)) { throw 'Нет receipt нашего процесса; чужие процессы не останавливаю.' }
$viewerState = Get-Content -Raw -Encoding UTF8 $viewer.Process | ConvertFrom-Json
$viewerOwned = Get-CimInstance Win32_Process -Filter "ProcessId = $($viewerState.process_id)"
if (-not $viewerOwned) { Write-Output 'Процесс просмотрщика уже завершён.'; return }
if ($viewerOwned.ExecutablePath -ne $viewer.Node -or
  -not $viewerOwned.CommandLine.Contains($viewer.Entry) -or -not $viewerOwned.CommandLine.Contains($viewer.Preload)) {
  throw 'Идентичность процесса не подтверждена; остановка запрещена.'
}
$viewerListeners = @(Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue)
if ($viewerListeners.Count -ne 1 -or $viewerListeners[0].OwningProcess -ne $viewerState.process_id -or
  $viewerListeners[0].LocalAddress -ne '127.0.0.1') { throw 'Владелец HTTP не подтверждён; остановка запрещена.' }
Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8099/' -SessionVariable viewerSession | Out-Null
Invoke-RestMethod -Uri 'http://localhost:8099/api/server/shutdown' -Method Post -WebSession $viewerSession -Headers @{Origin='http://localhost:8099'} | Out-Null
for ($viewerAttempt=0; $viewerAttempt -lt 40; $viewerAttempt++) {
  if (-not (Get-Process -Id $viewerState.process_id -ErrorAction SilentlyContinue)) {
    Write-Output 'Наш просмотрщик остановлен штатно. Другие процессы и эмулятор не останавливались.'
    return
  }
  Start-Sleep -Milliseconds 250
}
throw 'Остановка не подтверждена; принудительное завершение и повторный запуск не выполнялись.'
