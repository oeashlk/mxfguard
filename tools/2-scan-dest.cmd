@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
call "%~dp0_common.cmd" || exit /b 1

echo.
echo ==========================================================
echo   ФАЗА 4 - Маніфест ПРИЙМАЧА (швидкий, тільки хеші)
echo ==========================================================
echo.
echo Відповідає на одне питання: чи те саме доїхало.
echo Про якість вмісту тут ще не йдеться - це 4-deep-validate.cmd
echo.

if not exist "%AUDIT%\src.csv" (
  echo [!] Не бачу %AUDIT%\src.csv
  echo     Маніфест джерела не робився? Тоді звіряти буде ні з чим.
  echo.
)

set "DST="
set /p "DST=Шлях до ПРИЙМАЧА (напр. E:\Media): "
if not defined DST goto :abort
if not exist "%DST%\" (
  echo [X] Каталог не існує: %DST%
  goto :abort
)

echo.
"%PY%" mxfguard.py scan --root "%DST%" --out "%AUDIT%\dst.csv" ^
    --checks hash --hash xxh128 --jobs 8 --resume

if errorlevel 1 (
  echo.
  echo [X] Скан завершився з помилкою.
) else (
  echo.
  echo [OK] Маніфест приймача: %AUDIT%\dst.csv
  echo Далі: 3-compare-report.cmd
)
:abort
echo.
pause
