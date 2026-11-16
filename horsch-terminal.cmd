@echo off
rem Abre o Horsch Terminal. Use "horsch-terminal.cmd --simular" para testar sem o SAP.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (python -m horsch_terminal %*) else (py -3 -m horsch_terminal %*)
if errorlevel 1 pause
