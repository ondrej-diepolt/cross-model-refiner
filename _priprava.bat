@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem Připraví prostředí .venv a nainstaluje závislosti. Volá ho spustit.bat, pokracovat.bat a porovnat.bat.

rem Najde Python 3.10+ (nejdřív spouštěč py, pak python v PATH).
set "PYTHON="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
    echo Nainstalujte Python 3.10 nebo novější z python.org ^(zaškrtněte ‚Add to PATH‘^).
    exit /b 1
)

rem Prostředí .venv se vytvoří jen poprvé.
if not exist ".venv\Scripts\python.exe" (
    echo Vytvářím prostředí .venv – jen při prvním spuštění, chvíli to potrvá...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo Prostředí .venv se nepodařilo vytvořit.
        exit /b 1
    )
)

rem Závislosti se instalují jen tehdy, když se requirements.txt liší od naposledy nainstalovaného.
fc /b requirements.txt ".venv\requirements.nainstalovano" >nul 2>&1
if errorlevel 1 (
    echo Instaluji závislosti z requirements.txt...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Instalace závislostí se nepodařila. Zkontrolujte připojení k internetu a spusťte znovu.
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements.nainstalovano" >nul
)
exit /b 0
