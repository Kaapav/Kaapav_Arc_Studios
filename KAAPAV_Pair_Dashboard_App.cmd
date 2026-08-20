@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0show_dashboard_app_pairing_code.ps1"
if errorlevel 1 pause
