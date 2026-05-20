@echo off
REM Opens the transcriber log file in Notepad.

set "HERE=%~dp0"
set "LOGFILE=%HERE%logs\transcribe.log"

if not exist "%LOGFILE%" (
    echo No log file yet. Has the service been started?
    pause
    exit /b 1
)

start "" notepad "%LOGFILE%"
