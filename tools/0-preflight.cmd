@echo off
chcp 65001 >nul
setlocal
rem UNC-сумісний перехід у теку інструменту. Звичайний "cd /d" на
rem мережевому шляху падає, cmd мовчки лишається в C:\Windows і бере
rem системний рантайм замість комплектного. pushd мапить тимчасову
rem літеру диска і працює однаково локально та з шари.
pushd "%~dp0.." 2>nul || (
  echo [X] Не вдалося відкрити теку інструменту: %~dp0..
  echo     Якщо це мережева шара - скопіюй теку локально.
  pause
  exit /b 1
)
set "MG_ROOT=%CD%"

echo.
echo ==========================================================
echo   mxfguard - перевірка середовища
echo ==========================================================
echo.

rem --- Python ---
set "PY="
set "PYKIND="
if exist "tools\python\python.exe" (
  set "PY=tools\python\python.exe"
  set "PYKIND=з комплекту"
) else (
  for %%P in (python.exe) do if not defined PY set "PY=%%~$PATH:P"
  if not defined PY (where py >nul 2>&1 && set "PY=py")
  set "PYKIND=системний"
)

if not defined PY (
  echo [X] Python НЕ ЗНАЙДЕНО і в комплекті його немає.
  echo     Це збірка без рантайму. Або візьми повний архів,
  echo     або постав Python:
  echo        winget install Python.Python.3.12
  echo     ВАЖЛИВО: галочка "Add python.exe to PATH".
  echo.
  goto :end
)
echo [OK] Python (%PYKIND%): %PY%
"%PY%" --version
"%PY%" -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)"
if errorlevel 1 (
  echo [X] Потрібен Python 3.9 або новіший. Онови.
  echo.
  goto :end
)
echo.

rem --- ffmpeg ---
echo --- ffmpeg / ffprobe ------------------------------------
if exist "tools\bin\ffprobe.exe" (
  echo [OK] ffprobe з комплекту: tools\bin\ffprobe.exe
  set "PATH=%MG_ROOT%\tools\bin;%PATH%"
) else (
  where ffprobe >nul 2>&1
  if errorlevel 1 (
    echo [!] ffprobe не знайдено. Перевірки struct і decode будуть ПРОПУЩЕНІ,
    echo     порятунок MXF теж недоступний. Решта працює.
    echo     Поставити: winget install Gyan.FFmpeg
  ) else (
    echo [OK] ffprobe знайдено в системі
  )
)
if exist "tools\bin\ffmpeg.exe" (
  echo [OK] ffmpeg з комплекту: tools\bin\ffmpeg.exe
) else (
  where ffmpeg >nul 2>&1
  if errorlevel 1 (
    echo [!] ffmpeg не знайдено - повний декод недоступний.
  ) else (
    echo [OK] ffmpeg знайдено в системі
  )
)
where mxf2raw >nul 2>&1
if errorlevel 1 (
  echo [i] mxf2raw немає - не обов'язково, додатковий MXF-валідатор.
) else (
  echo [OK] mxf2raw знайдено
)
echo.

rem --- xxhash ---
echo --- xxhash (швидкість хешування) ------------------------
"%PY%" -c "import xxhash" 2>nul
if errorlevel 1 (
  echo [!] Модуль xxhash не встановлено - хеш працюватиме на blake2b,
  echo     це приблизно у 8 разів повільніше.
  echo.
  choice /c YN /n /m "Встановити з локальної теки vendor зараз? [Y/N] "
  if errorlevel 2 goto :skipxx
  "%PY%" -m pip install --no-index --find-links vendor xxhash
  "%PY%" -c "import xxhash" 2>nul && echo [OK] xxhash встановлено || (
    echo [!] Не вдалося. Працюй на blake2b, це не критично.
  )
) else (
  echo [OK] xxhash встановлено
)
:skipxx
echo.

echo --- сам інструмент --------------------------------------
"%PY%" mxfguard.py --version
if errorlevel 1 (
  echo [X] mxfguard.py не запускається.
) else (
  echo [OK] mxfguard.py запускається
)
echo.
echo ==========================================================
echo   Якщо вище немає жодного [X] - можна працювати.
echo   Наступний крок: tests\selftest.cmd
echo ==========================================================

:end
echo.
popd
pause
