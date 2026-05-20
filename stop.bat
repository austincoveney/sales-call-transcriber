@echo off
REM Stops the transcriber service if it's running.

setlocal

powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*transcribe.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Stopped any running transcriber instances.
echo.
timeout /t 2 /nobreak >nul
