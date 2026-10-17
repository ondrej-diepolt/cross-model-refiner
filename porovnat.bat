@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Porovná dokončený běh s referenční nabídkou z examples/. Bez parametru poslední dokončený
rem běh v output/, jinak zadaná složka běhu (lze ji přetáhnout na tento soubor).
rem Jiná reference: porovnat.bat SLOZKA --reference cesta\k\nabidce.docx
call "%~dp0_priprava.bat" || goto konec
.venv\Scripts\python.exe -m refiner porovnat %*
:konec
pause
