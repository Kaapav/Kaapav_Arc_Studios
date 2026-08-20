@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo KAAPAV Python environment is missing.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -u configure_meta.py
set "KAAPAV_META_EXIT=%ERRORLEVEL%"
echo.
if not "%KAAPAV_META_EXIT%"=="0" echo Meta connection did not pass. Nothing will publish.
pause
exit /b %KAAPAV_META_EXIT%
