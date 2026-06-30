@echo off
setlocal
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -File scripts\update_report.ps1
pause
