@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Dokončí přerušený běh. Bez parametru poslední přerušený v output/, jinak zadaná složka běhu.
call "%~dp0_priprava.bat" || goto konec
.venv\Scripts\python.exe -m refiner --pokracovat %*
:konec
pause
