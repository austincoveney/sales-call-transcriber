@echo off
REM Reports whether the transcriber service is currently running.

setlocal

powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*transcribe.py*' }) { Write-Host 'RUNNING' -ForegroundColor Green } else { Write-Host 'NOT RUNNING' -ForegroundColor Yellow }"

echo.
echo If NOT RUNNING, double-click run.bat to start it.
echo.
pause
