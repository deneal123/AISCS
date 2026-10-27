# Установка только в пользовательский каталог, без служб, PATH и обновления Windows.
. (Join-Path $PSScriptRoot 'environment.ps1')
$viewer = Get-MobileViewerPaths
New-Item -ItemType Directory -Path (Split-Path -Parent $viewer.Archive) -Force | Out-Null
if (-not (Test-Path -LiteralPath $viewer.Archive)) {
  Invoke-WebRequest -Uri 'https://github.com/bilbospocketses/ws-scrcpy-web/releases/download/v0.5.10/WsScrcpyWeb-stable-Portable.zip' -OutFile $viewer.Archive
}
Assert-MobileViewerArchive $viewer.Archive

Add-Type -AssemblyName System.IO.Compression.FileSystem
$viewerRuntime = Join-Path $viewer.Base 'runtime'
$viewerZip = [System.IO.Compression.ZipFile]::OpenRead($viewer.Archive)
try {
  $viewerBoundary = [System.IO.Path]::GetFullPath($viewerRuntime) + [System.IO.Path]::DirectorySeparatorChar
  foreach ($viewerEntry in $viewerZip.Entries) {
    $viewerTarget = [System.IO.Path]::GetFullPath((Join-Path $viewerRuntime $viewerEntry.FullName))
    if (-not $viewerTarget.StartsWith($viewerBoundary, [StringComparison]::OrdinalIgnoreCase)) {
      throw 'Архив содержит путь за пределами каталога установки.'
    }
  }
  if (-not (Test-Path -LiteralPath $viewerRuntime)) {
    Expand-Archive -LiteralPath $viewer.Archive -DestinationPath $viewerRuntime
  }
  # Не перезаписываем изменённую установку. Сверяем существующие файлы с архивом.
  foreach ($viewerEntry in $viewerZip.Entries) {
    if (-not $viewerEntry.Name) { continue }
    $viewerTarget = Join-Path $viewerRuntime $viewerEntry.FullName
    if ($viewerEntry.FullName -eq 'Update.exe' -and (Test-Path -LiteralPath $viewer.DisabledUpdater)) {
      $viewerTarget = $viewer.DisabledUpdater
    }
    if (-not (Test-Path -LiteralPath $viewerTarget -PathType Leaf)) { throw 'Установка неполная; отсутствует файл архива.' }
    $viewerStream = $viewerEntry.Open()
    $viewerHash = [System.Security.Cryptography.SHA256]::Create()
    try { $viewerExpected = ([BitConverter]::ToString($viewerHash.ComputeHash($viewerStream))).Replace('-', '') }
    finally { $viewerStream.Dispose(); $viewerHash.Dispose() }
    if ((Get-FileHash -LiteralPath $viewerTarget -Algorithm SHA256).Hash -ne $viewerExpected) {
      throw 'Файл установленного просмотрщика изменён. Автоматическая перезапись запрещена.'
    }
  }
} finally { $viewerZip.Dispose() }

# Убираем только marker обновления нашей новой установки, сохраняя его восстанавливаемо.
$viewerUpdater = Join-Path $viewerRuntime 'Update.exe'
if (Test-Path -LiteralPath $viewerUpdater) {
  if (Test-Path -LiteralPath $viewer.DisabledUpdater) { throw 'Оба updater-файла существуют; автоматическая замена запрещена.' }
  foreach ($viewerMoveTarget in @($viewerUpdater,$viewer.DisabledUpdater)) {
    if (-not ([System.IO.Path]::GetFullPath($viewerMoveTarget)).StartsWith(
      ([System.IO.Path]::GetFullPath($viewer.Base) + [System.IO.Path]::DirectorySeparatorChar),
      [StringComparison]::OrdinalIgnoreCase)) { throw 'Путь updater выходит за каталог просмотрщика.' }
  }
  New-Item -ItemType Directory -Path (Split-Path -Parent $viewer.DisabledUpdater) -Force | Out-Null
  Move-Item -LiteralPath $viewerUpdater -Destination $viewer.DisabledUpdater
}

$viewerPackage = Get-Content -Raw -Encoding UTF8 (Join-Path $viewer.Current 'package.json') | ConvertFrom-Json
if ($viewerPackage.version -ne '0.5.10') { throw 'Неподдерживаемая версия просмотрщика.' }
New-Item -ItemType Directory -Path $viewer.Data,$viewer.Dependencies,$viewer.Logs -Force | Out-Null
$viewerSdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk/platform-tools'
$viewerCopies = @(
  @{ Source = Join-Path $viewerSdk 'adb.exe'; Target = $viewer.Adb },
  @{ Source = Join-Path $viewerSdk 'AdbWinApi.dll'; Target = Join-Path $viewer.Dependencies 'adb/AdbWinApi.dll' },
  @{ Source = Join-Path $viewerSdk 'AdbWinUsbApi.dll'; Target = Join-Path $viewer.Dependencies 'adb/AdbWinUsbApi.dll' },
  @{ Source = Join-Path $viewer.Current 'seed/scrcpy-server/scrcpy-server'; Target = Join-Path $viewer.Dependencies 'scrcpy-server/scrcpy-server' },
  @{ Source = $viewer.Node; Target = $viewer.CacheNode }
)
foreach ($viewerCopy in $viewerCopies) {
  if (-not (Test-Path -LiteralPath $viewerCopy.Source -PathType Leaf)) { throw 'Не найден обязательный файл SDK или seed.' }
  New-Item -ItemType Directory -Path (Split-Path -Parent $viewerCopy.Target) -Force | Out-Null
  if (Test-Path -LiteralPath $viewerCopy.Target) {
    if ((Get-FileHash -LiteralPath $viewerCopy.Source).Hash -ne (Get-FileHash -LiteralPath $viewerCopy.Target).Hash) {
      throw 'Файл зависимостей изменён. Автоматическая перезапись запрещена.'
    }
  } else { Copy-Item -LiteralPath $viewerCopy.Source -Destination $viewerCopy.Target }
}

if (-not (Test-Path -LiteralPath $viewer.Config)) {
  Write-MobileViewerJson ([ordered]@{
    installMode = 'user'; firstRunComplete = $true; webPort = 8099
    autoUpdate = $false; updateCheckIntervalMinutes = 1440; channel = 'stable'
    dependenciesPath = $viewer.Dependencies; adbPath = $viewer.Adb
    allowedHosts = @('localhost','127.0.0.1'); frameAncestors = @(); scanConcurrency = 1
  }) $viewer.Config
}
Write-MobileViewerJson ([ordered]@{
  version = '0.5.10'; archive_sha256 = (Get-FileHash -LiteralPath $viewer.Archive).Hash
  node_sha256 = (Get-FileHash -LiteralPath $viewer.Node).Hash
  cache_node_sha256 = (Get-FileHash -LiteralPath $viewer.CacheNode).Hash
  entry_sha256 = (Get-FileHash -LiteralPath $viewer.Entry).Hash
  adb_sha256 = (Get-FileHash -LiteralPath $viewer.Adb).Hash
}) $viewer.Receipt
Write-Output 'Просмотрщик установлен. Сервер, ADB и эмулятор не запускались.'
