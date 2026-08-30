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
call tools\_common.cmd || exit /b 1

echo.
echo ==========================================================
echo   Порятунок есенції з MXF із зашифрованою головою
echo ==========================================================
echo.
echo Працює після 5-ransomware-triage.cmd. Бере файли, у яких
echo знайдено salvage_offset, і витягує з них картинку.
echo.
echo ЩО ВИХОДИТЬ:  сам матеріал - картинка і рух.
echo ЩО НЕ ВИХОДИТЬ: таймкод, аудіодоріжки, метадані MXF -
echo                 вони жили в заголовку, який знищено.
echo.
echo Джерело не змінюється, результат пишеться окремо.
echo.

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [X] Потрібен ffmpeg. Постав: winget install Gyan.FFmpeg
  goto :abort
)

if not exist "%AUDIT%\quarantine.csv" (
  echo [!] Не бачу %AUDIT%\quarantine.csv
  echo     Спочатку запусти 5-ransomware-triage.cmd
  echo.
)

set "Q="
set /p "Q=Шлях до карантину (той самий, що й у фазі 1): "
if not defined Q goto :abort
if not exist "%Q%\" (
  echo [X] Каталог не існує: %Q%
  goto :abort
)

set "OUT=%AUDIT%\salvaged"
echo.
echo Результат буде тут: %OUT%
echo.

"%PY%" tools\salvage.py --csv "%AUDIT%\quarantine.csv" --root "%Q%" --outdir "%OUT%"

echo.
echo ==========================================================
echo   ОБОВ'ЯЗКОВО: відкрий *.preview.png і подивись очима.
echo   Інструмент не вміє відрізнити реальний сюжет від
echo   кольорового шуму - це може зробити тільки людина.
echo ==========================================================
if exist "%OUT%" start "" "%OUT%"
:abort
echo.
popd
pause
