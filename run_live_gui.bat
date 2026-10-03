@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python -m app.main
if errorlevel 1 pause
