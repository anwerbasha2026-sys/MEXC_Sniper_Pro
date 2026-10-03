@echo off
setlocal
cd /d "%~dp0"
python -m app.gui
if errorlevel 1 (
  echo.
  echo MEXC Sniper GUI exited with an error.
  pause
)
endlocal
