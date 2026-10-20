@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Start a new run from input/. Free offline demo: run.bat --dry-run
call "%~dp0_setup.bat" || goto finish
.venv\Scripts\python.exe -m refiner %*
:finish
pause
