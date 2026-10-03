@echo off
setlocal
python -m pip install --upgrade buildozer
buildozer android debug
endlocal
