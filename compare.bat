@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Compare the latest completed run, or a supplied directory, against examples/.
rem Alternate reference: compare.bat DIRECTORY --reference path\to\offer.docx
call "%~dp0_setup.bat" || goto finish
.venv\Scripts\python.exe -m refiner compare %*
:finish
pause
