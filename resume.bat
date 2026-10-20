@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Resume the latest interrupted run, or the supplied run directory.
call "%~dp0_setup.bat" || goto finish
.venv\Scripts\python.exe -m refiner --resume %*
:finish
pause
