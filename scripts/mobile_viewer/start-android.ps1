param([switch]$CheckOnly)
. (Join-Path $PSScriptRoot 'environment.ps1')
$viewer = Get-MobileViewerPaths
$viewerEmulator = Join-Path $env:LOCALAPPDATA 'Android/Sdk/emulator/emulator.exe'
if (-not (Test-Path -LiteralPath $viewerEmulator -PathType Leaf)) { throw 'Android Emulator не установлен.' }
$viewerAvds = @(& $viewerEmulator -list-avds)
if ($LASTEXITCODE -ne 0 -or $viewerAvds -notcontains 'GPTHub_Mobile_API35') { throw 'Не найден созданный для GPTHub AVD.' }
$viewerOs = Get-CimInstance Win32_OperatingSystem
$viewerFreeGiB = $viewerOs.FreePhysicalMemory / 1MB
$viewerIssues = @()
if ($viewerFreeGiB -lt 4) { $viewerIssues += 'Недостаточно RAM: требуется минимум4 ГБ свободной памяти.' }
$viewerRuntimeStatus = (& (Join-Path $PSScriptRoot 'status.ps1')) | ConvertFrom-Json
if (-not $viewerRuntimeStatus.http_ready) { $viewerIssues += 'Сначала запустите принадлежащий этому проекту HTTP-просмотрщик.' }
foreach ($viewerPort in @(5580,5581)) {
  if (@(Get-NetTCPConnection -LocalPort $viewerPort -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
    $viewerIssues += "Порт $viewerPort уже занят; повторный эмулятор не запускается."
  }
}
$viewerAdbListeners = @(Get-NetTCPConnection -LocalPort 5038 -State Listen -ErrorAction SilentlyContinue)
if ($viewerAdbListeners.Count -ne 1 -or $viewerAdbListeners[0].LocalAddress -ne '127.0.0.1') {
  $viewerIssues += 'Сначала запустите локальный просмотрщик с его отдельным ADB.'
} else {
  $viewerAdbProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($viewerAdbListeners[0].OwningProcess)"
  if (-not $viewerAdbProcess -or $viewerAdbProcess.ExecutablePath -ne $viewer.Adb) {
    $viewerIssues += 'Владелец ADB-порта не подтверждён.'
  }
}
if ($CheckOnly) {
  [ordered]@{ ready = $viewerIssues.Count -eq 0; free_ram_gib = [math]::Round($viewerFreeGiB,2)
    minimum_boot_ram_gib = 4; issues = @($viewerIssues) } | ConvertTo-Json
  return
}
if ($viewerIssues.Count -gt 0) { throw ($viewerIssues -join ' ') }
$viewerAdbPortBefore = [Environment]::GetEnvironmentVariable('ANDROID_ADB_SERVER_PORT', 'Process')
try {
  [Environment]::SetEnvironmentVariable('ANDROID_ADB_SERVER_PORT', '5038', 'Process')
  $viewerStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $viewerLaunch = Start-Process -FilePath $viewerEmulator -ArgumentList @('-avd','GPTHub_Mobile_API35',
    '-port','5580','-memory','2048','-cores','2','-gpu','auto','-no-window','-no-audio','-no-snapshot','-no-metrics') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $viewer.Logs "$viewerStamp.android.stdout.log") -RedirectStandardError (Join-Path $viewer.Logs "$viewerStamp.android.stderr.log")
} finally { [Environment]::SetEnvironmentVariable('ANDROID_ADB_SERVER_PORT', $viewerAdbPortBefore, 'Process') }
Write-Output "Запущен только GPTHub_Mobile_API35 (launcher PID $($viewerLaunch.Id)). Готовность Android ещё не подтверждена; проверьте http://localhost:8099."
