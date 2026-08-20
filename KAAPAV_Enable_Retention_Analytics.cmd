@echo off
setlocal
cd /d "%~dp0"
echo KAAPAV YouTube Analytics authorization
echo Google requires one owner consent. Existing upload access stays protected.
echo.
.venv\Scripts\python.exe -u authorize_youtube_analytics.py --open-console --wait-minutes 10
echo.
pause
