@echo off
REM Starts the transcriber service. Safe to run multiple times -
REM transcribe.py uses a named mutex so only one instance ever runs.

set "HERE=%~dp0"

echo Starting Sales Call Transcriber...
start "" /B "%HERE%.venv\Scripts\pythonw.exe" "%HERE%transcribe.py"

echo.
echo Service launched in the background.
echo Drop MP3s into the "Sales Calls - Inbox" folder on your desktop.
echo You can close this window.
echo.
timeout /t 3 /nobreak >nul
