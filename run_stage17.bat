@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
if not exist .env copy /Y .env.example .env
python .\app\gui.py
pause
