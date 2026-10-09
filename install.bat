@echo off
cd /d "%~dp0"
py -3 "%~dp0install.py"
if errorlevel 1 python "%~dp0install.py"
pause
