@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title mxfguard - перевірка медіа-архіву

rem UNC-сумісний перехід у теку інструменту.
pushd "%~dp0" 2>nul || (
  echo [X] Не вдалося відкрити теку інструменту: %~dp0
  pause
  exit /b 1
)

call tools\_common.cmd || (popd & exit /b 1)

:menu
cls
echo.
echo  ==============================================================
echo    mxfguard 1.0    перевірка медіа-архіву при переносі даних
echo  ==============================================================
echo.
echo    Машина     : %COMPUTERNAME%
echo    Рантайм    : Python %MG_PY%, ffmpeg %MG_FF%
echo    Маніфести  : %AUDIT%
echo.
echo  --- ПІДГОТОВКА ------------------------------------------------
echo.
echo    0   Перевірити середовище
echo    9   Самоперевірка ^(доводить, що поломки ловляться^)
echo.
echo  --- ПЕРЕНОС ---------------------------------------------------
echo.
echo    1   Маніфест ДЖЕРЕЛА          до копіювання
echo    2   Маніфест ПРИЙМАЧА         після копіювання
echo    3   Звірка і звіт
echo    4   Контентна валідація       довго, на ніч
echo.
echo  --- ШИФРУВАЛЬНИК ----------------------------------------------
echo.
echo    5   Оцінка шкоди по карантину
echo    6   Порятунок есенції з побитих MXF
echo.
echo  --- ДОВІДКА ---------------------------------------------------
echo.
echo    M   Мануал адміністратора        R   Рунбук переносу
echo    A   Змінити теку маніфестів      Q   Вихід
echo.

set "SEL="
set /p "SEL=  Вибір: "
if not defined SEL goto menu

rem прибрати лапки і пробіли, якщо вставили зайве
set "SEL=%SEL: =%"
set "SEL=%SEL:"=%"

if /i "%SEL%"=="0" call tools\0-preflight.cmd & goto menu
if /i "%SEL%"=="9" call tests\selftest.cmd & goto menu
if /i "%SEL%"=="1" call tools\1-scan-source.cmd & goto menu
if /i "%SEL%"=="2" call tools\2-scan-dest.cmd & goto menu
if /i "%SEL%"=="3" call tools\3-compare-report.cmd & goto menu
if /i "%SEL%"=="4" call tools\4-deep-validate.cmd & goto menu
if /i "%SEL%"=="5" call tools\5-ransomware-triage.cmd & goto menu
if /i "%SEL%"=="6" call tools\salvage-mxf.cmd & goto menu
rem Літери продубльовані під українську розкладку: на тих самих
rem клавішах лежать Ь(M), К(R), Ф(A), Й(Q). Перемикати розкладку
rem заради одного символу - зайвий крок посеред роботи.
if /i "%SEL%"=="M" start "" "docs\MANUAL.html" & goto menu
if /i "%SEL%"=="Ь" start "" "docs\MANUAL.html" & goto menu
if /i "%SEL%"=="R" start "" "docs\mxfguard-runbook.html" & goto menu
if /i "%SEL%"=="К" start "" "docs\mxfguard-runbook.html" & goto menu
if /i "%SEL%"=="A" goto setaudit
if /i "%SEL%"=="Ф" goto setaudit
if /i "%SEL%"=="Q" goto done
if /i "%SEL%"=="Й" goto done

echo.
echo   Немає такого пункту: %SEL%
timeout /t 2 >nul
goto menu

:setaudit
echo.
echo   Зараз маніфести пишуться в:
echo     %AUDIT%
echo.
echo   Тека має бути ПОЗА деревом, яке скануєш, інакше маніфест
echo   потрапить у власний скан і в наступний перенос.
echo.
set "NEWAUDIT="
set /p "NEWAUDIT=  Нова тека (Enter - лишити як є): "
if not defined NEWAUDIT goto menu
set "NEWAUDIT=%NEWAUDIT:"=%"
if not exist "%NEWAUDIT%" mkdir "%NEWAUDIT%" 2>nul
if not exist "%NEWAUDIT%\" (
  echo   [X] Не вдалося створити: %NEWAUDIT%
  pause
  goto menu
)
set "AUDIT=%NEWAUDIT%"
echo   [OK] Тепер маніфести йдуть у %AUDIT%
timeout /t 2 >nul
goto menu

:done
popd
endlocal
exit /b 0
