@echo off
setlocal
cd /d "%~dp0"
title KAAPAV ARC Studios - Safe Recovery
"%~dp0.venv\Scripts\python.exe" -u "%~dp0kaapav_recovery.py"
set "KAAPAV_RECOVERY_EXIT=%ERRORLEVEL%"
echo.
if "%KAAPAV_RECOVERY_EXIT%"=="0" (
  echo Recovery finished successfully. You can close this window.
) else (
  echo Recovery stopped safely. Read the message above or open the dashboard.
)
pause
exit /b %KAAPAV_RECOVERY_EXIT%
