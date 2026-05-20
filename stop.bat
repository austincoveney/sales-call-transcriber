@echo off
REM Stops any running transcriber processes.

taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq Sales Call*" >nul 2>&1
wmic process where "name='pythonw.exe' and commandline like '%%transcribe.py%%'" delete >nul 2>&1
echo Stopped.
