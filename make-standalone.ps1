<#
.SYNOPSIS
  Відновлює комплектний рантайм і збирає обидва архіви mxfguard.

.DESCRIPTION
  У git не трекаються tools\bin\ (ffmpeg + ffprobe, по ~212 МБ) і
  tools\python\ (embeddable Python). Цей скрипт кладе їх на місце,
  щоб зі свіжого клону можна було зібрати автономну збірку.

  Що робиться:
    1. tools\python\  — качається python-X.Y.Z-embed-amd64.zip з python.org,
                        у нього розпаковується колесо xxhash із vendor\
    2. tools\bin\     — беруться ffmpeg.exe і ffprobe.exe: спершу з PATH,
                        інакше вкажи -FfmpegDir
    3. збираються mxfguard-1.0.zip (легка) і -standalone.zip (повна)

  Ідемпотентний: наявні теки не перезбираються, якщо не вказано -Force.

.EXAMPLE
  .\make-standalone.ps1
  .\make-standalone.ps1 -FfmpegDir "C:\ffmpeg\bin" -Force
#>
[CmdletBinding()]
param(
  [string]$PythonVersion = "3.13.15",
  [string]$FfmpegDir,
  [string]$OutDir = "..",
  [string]$ToDrive,
  [switch]$Force,
  [switch]$SkipArchives
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say($m) { Write-Host "[i] $m" }
function Ok($m)  { Write-Host "[OK] $m" -ForegroundColor Green }
function Die($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- Python
$pyDir = Join-Path $PSScriptRoot "tools\python"
if ((Test-Path "$pyDir\python.exe") -and -not $Force) {
  Ok "tools\python\ вже на місці (перезібрати: -Force)"
} else {
  if ($Force -and (Test-Path $pyDir)) { Remove-Item $pyDir -Recurse -Force }
  New-Item -ItemType Directory -Force $pyDir | Out-Null

  $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
  $tmp = Join-Path ([IO.Path]::GetTempPath()) "python-embed-$PythonVersion.zip"
  Say "качаю $url"
  try {
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
  } catch {
    Die "не вдалося завантажити Python $PythonVersion. Перевір версію на python.org/ftp/python/"
  }
  Expand-Archive $tmp -DestinationPath $pyDir -Force
  Remove-Item $tmp -Force
  Ok "Python $PythonVersion розпаковано"

  # xxhash: колесо просто розгортається поруч із python.exe —
  # embeddable-збірка тримає власну теку в sys.path через ._pth
  $tag = "cp" + ($PythonVersion -split '\.')[0] + ($PythonVersion -split '\.')[1]
  $whl = Get-ChildItem "$PSScriptRoot\vendor\xxhash-*-$tag-$tag-win_amd64.whl" -EA SilentlyContinue |
         Select-Object -First 1
  if (-not $whl) {
    Write-Host "[!] немає колеса xxhash під $tag — хеш працюватиме на blake2b" -ForegroundColor Yellow
  } else {
    $stage = Join-Path ([IO.Path]::GetTempPath()) "xxh-$tag"
    Remove-Item $stage -Recurse -Force -EA SilentlyContinue
    Expand-Archive $whl.FullName -DestinationPath $stage -Force
    Copy-Item "$stage\*" $pyDir -Recurse -Force
    Remove-Item $stage -Recurse -Force
    Ok "xxhash вбудовано ($($whl.Name))"
  }

  & "$pyDir\python.exe" -c "import xxhash,sys; print('    Python',sys.version.split()[0],'| xxhash',xxhash.VERSION)"
  if ($LASTEXITCODE -ne 0) { Die "вбудований Python не запускається" }
}

# ---------------------------------------------------------------- ffmpeg
$binDir = Join-Path $PSScriptRoot "tools\bin"
if ((Test-Path "$binDir\ffmpeg.exe") -and (Test-Path "$binDir\ffprobe.exe") -and -not $Force) {
  Ok "tools\bin\ вже на місці (перезібрати: -Force)"
} else {
  New-Item -ItemType Directory -Force $binDir | Out-Null
  if (-not $FfmpegDir) {
    $src = (Get-Command ffmpeg -EA SilentlyContinue).Source
    if (-not $src) {
      Die "ffmpeg не знайдено в PATH. Постав (winget install Gyan.FFmpeg) або вкажи -FfmpegDir"
    }
    $FfmpegDir = Split-Path $src
  }
  foreach ($exe in "ffmpeg.exe", "ffprobe.exe") {
    $p = Join-Path $FfmpegDir $exe
    if (-not (Test-Path $p)) { Die "немає $p" }
    Copy-Item $p $binDir -Force
  }
  $mb = ((Get-ChildItem $binDir | Measure-Object Length -Sum).Sum / 1MB)
  Ok ("ffmpeg і ffprobe скопійовано з {0} ({1:N0} МБ)" -f $FfmpegDir, $mb)
}

# ------------------------------------------------------- спільні виключення
$Skip = @('.git', '.gitignore', '.gitattributes', 'make-standalone.ps1')

function Copy-Payload {
  <#
    Розкладає вміст інструменту в теку призначення.
    -Lean прибирає комплектний рантайм (tools\bin, tools\python).
    -Usb додає autorun.inf, іконку та ярлик з українською назвою.
  #>
  param([string]$Dest, [switch]$Lean, [switch]$Usb)

  Remove-Item $Dest -Recurse -Force -EA SilentlyContinue
  New-Item -ItemType Directory -Force "$Dest\tools" | Out-Null

  $rootSkip = $Skip
  if (-not $Usb) { $rootSkip += @('autorun.inf', 'mxfguard.ico') }

  Get-ChildItem $PSScriptRoot -Exclude ($rootSkip + 'tools') -Force |
    Where-Object { $_.Name -notlike '.git*' } |
    Copy-Item -Destination $Dest -Recurse -Force
  $toolSkip = if ($Lean) { @('bin', 'python') } else { @() }
  Get-ChildItem "$PSScriptRoot\tools" -Exclude $toolSkip |
    Copy-Item -Destination "$Dest\tools" -Recurse -Force

  if ($Usb) {
    # Лаунчер названо ASCII, бо autorun.inf читається в ANSI-кодуванні
    # системи і кириличне ім'я файлу в ньому не переживе. Українську
    # назву в Провіднику дає ця обгортка.
    #
    # Саме .cmd, а не .lnk: ярлик на змінному носії мусив би або
    # тримати абсолютний шлях (літера диска щоразу інша), або
    # покладатися на те, як оболонка тлумачить порожню робочу теку.
    # %~dp0 не залежить ні від того, ні від іншого.
    $wrap = @(
      '@echo off',
      'rem Обгортка з українською назвою. Уся логіка - у START.cmd.',
      'call "%~dp0START.cmd" %*'
    ) -join "`r`n"
    [IO.File]::WriteAllText("$Dest\ЗАПУСТИТИ.cmd", $wrap + "`r`n",
                            (New-Object Text.UTF8Encoding $false))
  }
}

# ------------------------------------------------------------ запис на диск
if ($ToDrive) {
  $d = $ToDrive.TrimEnd('\')
  if ($d -notmatch '^[A-Za-z]:$') { Die "вкажи літеру диска, напр. -ToDrive E:" }
  if (-not (Test-Path "$d\")) { Die "диск $d недоступний" }

  $vol = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$d'"
  if ($vol.DriveType -ne 2) {
    Write-Host "[!] $d не є знімним диском (DriveType=$($vol.DriveType))." -ForegroundColor Yellow
    # У неінтерактивному режимі відповіді не буде - тоді відмовляємось,
    # бо мовчазний запис у корінь чужого диска гірший за зупинку.
    try { $a = Read-Host "    Все одно писати? [y/N]" }
    catch { Die "не знімний диск, а підтвердити нікому (неінтерактивний режим)" }
    if ($a -notmatch '^[yYtTдД]') { Die "скасовано" }
  }
  $freeMb = [int]($vol.FreeSpace / 1MB)
  if ($freeMb -lt 500) { Die "на $d лише $freeMb МБ вільно, потрібно від 500 МБ" }

  Say "пишу на $d ($($vol.VolumeName), вільно $freeMb МБ)"
  Copy-Payload -Dest "$d\" -Usb
  try {
    $vol | Set-CimInstance -Property @{ VolumeName = 'mxfguard' } -EA Stop
    Ok "мітку тому змінено на mxfguard"
  } catch {
    Write-Host "[!] мітку тому не змінено (потрібні права): $_" -ForegroundColor Yellow
  }
  Ok "флешка готова: $d"
  Write-Host ""
  Say "Windows 7+ не запускає програми з флешки автоматично - це вимкнено"
  Say "в самій ОС. Робочий шлях: відкрити диск і клацнути ЗАПУСТИТИ"
  Say "(або START.cmd). Іконка й мітка диска підхопляться з autorun.inf."
  exit 0
}

if ($SkipArchives) { Say "архіви пропущено (-SkipArchives)"; exit 0 }

# ---------------------------------------------------------------- архіви
$OutDir = (Resolve-Path $OutDir).Path
$lean   = Join-Path $OutDir "mxfguard-1.0.zip"
$full   = Join-Path $OutDir "mxfguard-1.0-standalone.zip"
$usb    = Join-Path $OutDir "mxfguard-1.0-usb.zip"
Remove-Item $lean, $full, $usb -Force -EA SilentlyContinue

$tmp = [IO.Path]::GetTempPath()
$builds = @(
  @{ Path = $lean; Stage = "mxfguard-lean";       Lean = $true;  Usb = $false },
  @{ Path = $full; Stage = "mxfguard-standalone"; Lean = $false; Usb = $false },
  @{ Path = $usb;  Stage = "mxfguard-usb";        Lean = $false; Usb = $true  }
)

foreach ($b in $builds) {
  $stage = Join-Path $tmp $b.Stage
  Copy-Payload -Dest $stage -Lean:$b.Lean -Usb:$b.Usb
  Compress-Archive "$stage\*" $b.Path -CompressionLevel Optimal
  Remove-Item $stage -Recurse -Force
}

foreach ($z in $lean, $full, $usb) {
  $i = Get-Item $z
  $size = if ($i.Length -gt 1MB) { "{0:N0} МБ" -f ($i.Length / 1MB) }
          else { "{0:N0} КБ" -f ($i.Length / 1KB) }
  Ok ("{0,-30} {1}" -f $i.Name, $size)
}

Write-Host ""
Say "перевір складене: tests\selftest.cmd"
