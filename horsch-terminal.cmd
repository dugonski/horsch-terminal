@echo off
rem Abre o Horsch Terminal. Use "horsch-terminal.cmd --simular" para testar sem o SAP.
setlocal
where py >nul 2>nul
if errorlevel 1 (python "%~dp0main.py" %*) else (py -3 "%~dp0main.py" %*)
if errorlevel 1 pause
