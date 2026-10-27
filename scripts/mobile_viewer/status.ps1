. (Join-Path $PSScriptRoot 'environment.ps1')
$viewer = Get-MobileViewerPaths
$viewerHttpReady = $false
$viewerAdbReady = $false
$viewerDeviceReady = $false
if (Test-Path -LiteralPath $viewer.Process) {
  $viewerState = Get-Content -Raw -Encoding UTF8 $viewer.Process | ConvertFrom-Json
  $viewerOwned = Get-CimInstance Win32_Process -Filter "ProcessId = $($viewerState.process_id)"
  if ($viewerOwned -and $viewerOwned.ExecutablePath -eq $viewer.Node -and
    $viewerOwned.CommandLine.Contains($viewer.Entry) -and $viewerOwned.CommandLine.Contains($viewer.Preload)) {
    $viewerHttp = @(Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue)
    $viewerHttpReady = $viewerHttp.Count -eq 1 -and $viewerHttp[0].LocalAddress -eq '127.0.0.1' -and
      $viewerHttp[0].OwningProcess -eq $viewerState.process_id
  }
}
$viewerAdbListeners = @(Get-NetTCPConnection -LocalPort 5038 -State Listen -ErrorAction SilentlyContinue)
if ($viewerAdbListeners.Count -eq 1 -and $viewerAdbListeners[0].LocalAddress -eq '127.0.0.1') {
  $viewerAdbProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($viewerAdbListeners[0].OwningProcess)"
  $viewerAdbReady = $viewerAdbProcess -and $viewerAdbProcess.ExecutablePath -eq $viewer.Adb
}
if ($viewerAdbReady) {
  try {
    $viewerAdbState = (& $viewer.Adb -H 127.0.0.1 -P 5038 devices 2>$null) -join "`n"
    $viewerDeviceReady = $LASTEXITCODE -eq 0 -and $viewerAdbState -match '(?m)^emulator-5580\s+device(?:\s|$)'
  } catch { $viewerAdbReady = $false }
}
$viewerOs = Get-CimInstance Win32_OperatingSystem
[ordered]@{
  url = 'http://localhost:8099'; http_ready = [bool]$viewerHttpReady
  adb_ready = [bool]$viewerAdbReady; emulator_connected = [bool]$viewerDeviceReady
  free_ram_gib = [math]::Round($viewerOs.FreePhysicalMemory / 1MB, 2)
  minimum_boot_ram_gib = 4
} | ConvertTo-Json
