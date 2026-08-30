@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
call "%~dp0_common.cmd" || exit /b 1

echo.
echo ==========================================================
echo   ФАЗА 1 - Оцінка шкоди від шифрувальника
echo ==========================================================
echo.
echo СПОЧАТКУ ПРОЧИТАЙ:
echo.
echo  1. Скануй з ЧИСТОГО середовища (Linux Live / WinPE),
echo     диск змонтований READ-ONLY. Хеш, порахований на
echo     скомпрометованій ОС, не підтверджує нічого.
echo  2. НЕ ВИДАЛЯЙ пошифровані файли. Більшість шифрувальників
echo     псують лише перші мегабайти великого MXF - тіло живе.
echo  3. Образ системного диска знімається ДО форматування.
echo     Заднім числом його не створити.
echo.
pause

set "Q="
set /p "Q=Шлях до карантину з пошкодженими файлами: "
if not defined Q goto :abort
if not exist "%Q%\" (
  echo [X] Каталог не існує: %Q%
  goto :abort
)

echo.
echo Рахую sha256 - повільніше, але маніфест придатний для акту.
echo.

"%PY%" mxfguard.py scan --root "%Q%" --out "%AUDIT%\quarantine.csv" ^
    --checks magic,entropy --ransomware --hash sha256 --jobs 4 --resume

"%PY%" mxfguard.py report --scan "%AUDIT%\quarantine.csv" ^
    --out "%AUDIT%\quarantine-report.html"

echo.
echo ==========================================================
echo   Як читати результат
echo ==========================================================
echo.
echo   ENCRYPTED          - мертвий увесь, рятувати нічого
echo   PARTIAL_ENCRYPTED  - голова мертва, ТІЛО ЖИВЕ
echo                        дивись стовпець salvage_offset
echo   RANSOM_NAME        - записка або дописане розширення
echo.
echo Для файлів PARTIAL_ENCRYPTED запусти salvage-mxf.cmd -
echo він витягне есенцію починаючи з salvage_offset.
echo.
echo Звіт: %AUDIT%\quarantine-report.html
choice /c YN /n /m "Відкрити звіт? [Y/N] "
if not errorlevel 2 start "" "%AUDIT%\quarantine-report.html"
:abort
echo.
pause
