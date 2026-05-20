@echo off
REM Launches the transcriber service hidden (no console window).
REM Used by Task Scheduler and for manual starts.

set "HERE=%~dp0"
start "" /B "%HERE%.venv\Scripts\pythonw.exe" "%HERE%transcribe.py"
