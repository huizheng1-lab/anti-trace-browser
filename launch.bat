@echo off
setlocal
cd /d "%~dp0"
start "" /B py main.py
endlocal
