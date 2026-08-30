@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
call "%~dp0_common.cmd" || exit /b 1

echo.
echo ==========================================================
echo   ФАЗА 4 - Звірка джерела з приймачем + звіт
echo ==========================================================
echo.

if not exist "%AUDIT%\src.csv" (
  echo [X] Немає %AUDIT%\src.csv - спочатку 1-scan-source.cmd
  goto :abort
)
if not exist "%AUDIT%\dst.csv" (
  echo [X] Немає %AUDIT%\dst.csv - спочатку 2-scan-dest.cmd
  goto :abort
)

"%PY%" mxfguard.py compare --src "%AUDIT%\src.csv" --dst "%AUDIT%\dst.csv" ^
    --out "%AUDIT%\diff.csv"
set "CMPRC=%errorlevel%"

echo.
if exist "%AUDIT%\dst_full.csv" (
  set "SCANCSV=%AUDIT%\dst_full.csv"
) else (
  set "SCANCSV=%AUDIT%\dst.csv"
)
"%PY%" mxfguard.py report --scan "%SCANCSV%" --compare "%AUDIT%\diff.csv" ^
    --out "%AUDIT%\report.html"

echo.
if "%CMPRC%"=="1" (
  echo ==========================================================
  echo   [!] Є розбіжності: MISSING / HASH_MISMATCH / SIZE_MISMATCH
  echo   Перенос НЕ чистий. Дивись звіт і перекопіюй проблемні.
  echo ==========================================================
) else (
  echo ==========================================================
  echo   [OK] Розбіжностей переносу немає.
  echo   Це ще не означає, що файли цілі - див. 4-deep-validate.cmd
  echo ==========================================================
)
echo.
echo Звіт: %AUDIT%\report.html
choice /c YN /n /m "Відкрити звіт зараз? [Y/N] "
if not errorlevel 2 start "" "%AUDIT%\report.html"
:abort
echo.
pause
