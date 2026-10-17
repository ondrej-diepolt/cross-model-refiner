@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Nový běh nad poptávkou z input/. Ukázka bez API a bez nákladů: spustit.bat --nanecisto
call "%~dp0_priprava.bat" || goto konec
.venv\Scripts\python.exe -m refiner %*
:konec
pause
