@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
call "%~dp0_common.cmd" || exit /b 1

echo.
echo ==========================================================
echo   ФАЗА 2 - Маніфест ДЖЕРЕЛА
echo ==========================================================
echo.
echo Знімок "як було" до копіювання. Без нього потім немає
echo з чим звіряти приймач.
echo.
echo Маніфести пишуться в: %AUDIT%
echo.

set "SRC="
set /p "SRC=Шлях до ДЖЕРЕЛА (напр. D:\Media): "
if not defined SRC goto :abort
if not exist "%SRC%\" (
  echo [X] Каталог не існує: %SRC%
  goto :abort
)

echo.
echo Обробляю %SRC% ...
echo Перервати можна Ctrl+C - потім запусти цей же скрипт ще раз,
echo він продовжить з місця зупинки.
echo.

"%PY%" mxfguard.py scan --root "%SRC%" --out "%AUDIT%\src.csv" ^
    --checks hash,magic,entropy --hash xxh128 --jobs 8 --resume

if errorlevel 1 (
  echo.
  echo [X] Скан завершився з помилкою.
) else (
  echo.
  echo [OK] Маніфест джерела: %AUDIT%\src.csv
  echo.
  echo ПЕРЕВІР ВРУЧНУ:
  echo   - кількість рядків у CSV = кількості файлів у дереві
  echo   - маніфест лежить ПОЗА деревом, яке скануєш
  echo.
  echo Далі: копіюй дані своїм інструментом (robocopy / FastCopy),
  echo потім запусти 2-scan-dest.cmd
)
:abort
echo.
pause
