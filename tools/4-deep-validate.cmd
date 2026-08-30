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
echo   ФАЗА 5 - Контентна валідація приймача
echo ==========================================================
echo.
echo Хеш каже лише, що файл не змінився при переносі, і чесно
echo переносить пошифроване сміття зі статусом OK.
echo Ця фаза дивиться ВСЕРЕДИНУ файлів.
echo.
echo ЦЕ ДОВГО. На десятки ТБ - ніч і більше.
echo Ctrl+C безпечний: --resume продовжить з місця зупинки.
echo.

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [!] ffmpeg не знайдено - декод буде пропущено,
  echo     лишаться magic/entropy/salvage. Це помітно слабша перевірка.
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
echo Глибина декодування:
echo   1 - повний декод кожного файлу (надійно, найдовше)
echo   2 - тільки перші й останні 30 с (швидкий димовий тест)
echo   3 - без декоду, лише структура (найшвидше)
echo.
choice /c 123 /n /m "Вибір [1/2/3]: "
set "DEEP=%errorlevel%"

set "CHECKS=hash,magic,entropy,struct,decode"
set "EDGES="
if "%DEEP%"=="2" set "EDGES=--decode-edges 30"
if "%DEEP%"=="3" set "CHECKS=hash,magic,entropy,struct"

echo.
echo Перевірки: %CHECKS% %EDGES%
echo Початок: %DATE% %TIME%
echo.

"%PY%" mxfguard.py scan --root "%DST%" --out "%AUDIT%\dst_full.csv" ^
    --checks %CHECKS% %EDGES% --ransomware --hash xxh128 ^
    --jobs 8 --decode-jobs 3 --resume

echo.
echo Кінець: %DATE% %TIME%
echo [OK] Повний маніфест: %AUDIT%\dst_full.csv
echo.
echo Далі запусти 3-compare-report.cmd - він підхопить dst_full.csv
echo і збере звіт з контентними статусами.
:abort
echo.
popd
pause
