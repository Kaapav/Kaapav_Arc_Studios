@echo off
title KAAPAV ARC Studios - Safe YouTube Upload
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Project Python environment not found.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -u studio_upload_shortcut.py
echo.
pause
