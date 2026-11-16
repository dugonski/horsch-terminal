@echo off
rem Abre o Macro App. Use "macro.cmd --simular" para testar sem o SAP.
setlocal
where py >nul 2>nul
if errorlevel 1 (python "%~dp0macro.py" %*) else (py -3 "%~dp0macro.py" %*)
if errorlevel 1 pause
