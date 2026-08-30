@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
call "%~dp0..\tools\_common.cmd" || exit /b 1
echo.
echo Самоперевірка створює тимчасове дерево з наперед відомими
echo поломками і звіряє, що інструмент їх ловить. Хвилина часу.
echo На бойові дані не впливає, після себе прибирає.
echo.
echo   Python: %MG_PY%   ffmpeg: %MG_FF%
echo.
"%PY%" selftest.py
echo.
pause
