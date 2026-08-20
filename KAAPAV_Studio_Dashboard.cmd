@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_studio_dashboard.ps1"
if errorlevel 1 pause
