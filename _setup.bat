@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem Prepare .venv and dependencies for run.bat, resume.bat, and compare.bat.

rem Find Python 3.10+, preferring the py launcher before python on PATH.
set "REFINER_PYTHON="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "REFINER_PYTHON=py -3"
if not defined REFINER_PYTHON (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "REFINER_PYTHON=python"
)
if not defined REFINER_PYTHON (
    echo Nainstalujte Python 3.10 nebo novější z python.org ^(zaškrtněte ‚Add to PATH‘^).
    exit /b 1
)

rem Create .venv only when missing.
if not exist ".venv\Scripts\python.exe" (
    echo Vytvářím prostředí .venv – jen při prvním spuštění, chvíli to potrvá...
    %REFINER_PYTHON% -m venv .venv
    if errorlevel 1 (
        echo Prostředí .venv se nepodařilo vytvořit.
        exit /b 1
    )
)

rem Install dependencies only when requirements.txt differs from the installed marker.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Instaluji závislosti z requirements.txt...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Instalace závislostí se nepodařila. Zkontrolujte připojení k internetu a spusťte znovu.
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements.installed" >nul
)
exit /b 0
