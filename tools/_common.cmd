@echo off
rem Спільна частина: підхопити вбудований рантайм, якщо він є,
rem інакше системний. Викликається з інших скриптів.
rem Порядок пріоритету: комплектні bin\ і python\ -> те, що в PATH.

set "MG_ROOT=%CD%"

rem --- ffmpeg/ffprobe з комплекту ---
if exist "%MG_ROOT%\tools\bin\ffmpeg.exe" (
  set "PATH=%MG_ROOT%\tools\bin;%PATH%"
  set "MG_FF=комплектний"
) else (
  set "MG_FF=системний"
)

rem --- Python з комплекту ---
set "PY="
if exist "%MG_ROOT%\tools\python\python.exe" (
  set "PY=%MG_ROOT%\tools\python\python.exe"
  set "MG_PY=комплектний"
) else (
  for %%P in (python.exe) do if not defined PY set "PY=%%~$PATH:P"
  if not defined PY (where py >nul 2>&1 && set "PY=py")
  set "MG_PY=системний"
)

if not defined PY (
  echo [X] Python не знайдено і в комплекті його немає.
  echo     Запусти 0-preflight.cmd, він підкаже що робити.
  pause
  exit /b 1
)

if not defined AUDIT set "AUDIT=C:\mxfguard-audit\%COMPUTERNAME%"
if not exist "%AUDIT%" mkdir "%AUDIT%" 2>nul
exit /b 0
