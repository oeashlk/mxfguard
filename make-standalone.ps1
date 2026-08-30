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

if ($SkipArchives) { Say "архіви пропущено (-SkipArchives)"; exit 0 }

# ---------------------------------------------------------------- архіви
$OutDir = (Resolve-Path $OutDir).Path
$lean   = Join-Path $OutDir "mxfguard-1.0.zip"
$full   = Join-Path $OutDir "mxfguard-1.0-standalone.zip"
Remove-Item $lean, $full -Force -EA SilentlyContinue

# легка: усе, крім комплектного рантайму
$stage = Join-Path ([IO.Path]::GetTempPath()) "mxfguard-lean"
Remove-Item $stage -Recurse -Force -EA SilentlyContinue
New-Item -ItemType Directory -Force "$stage\tools" | Out-Null
Get-ChildItem $PSScriptRoot -Exclude 'tools', '.git', '.gitignore', '.gitattributes', 'make-standalone.ps1' |
  Copy-Item -Destination $stage -Recurse -Force
Get-ChildItem "$PSScriptRoot\tools" -Exclude 'bin', 'python' |
  Copy-Item -Destination "$stage\tools" -Recurse -Force
Compress-Archive "$stage\*" $lean -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

# повна: з рантаймом
Get-ChildItem $PSScriptRoot -Exclude '.git', '.gitignore', '.gitattributes', 'make-standalone.ps1' |
  Compress-Archive -DestinationPath $full -CompressionLevel Optimal

foreach ($z in $lean, $full) {
  $i = Get-Item $z
  $size = if ($i.Length -gt 1MB) { "{0:N0} МБ" -f ($i.Length / 1MB) }
          else { "{0:N0} КБ" -f ($i.Length / 1KB) }
  Ok ("{0}  {1}" -f $i.Name, $size)
}

Write-Host ""
Say "перевір складене: tests\selftest.cmd"
