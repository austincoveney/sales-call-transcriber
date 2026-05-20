@echo off
REM Detailed status check: service state, backend, queue, recent activity.

setlocal
set "HERE=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%status.ps1"

echo.
pause
