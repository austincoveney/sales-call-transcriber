@echo off
setlocal

echo ==========================================
echo  Sales Call Transcriber - Setup
echo ==========================================
echo.

set "HERE=%~dp0"
pushd "%HERE%" || (echo Could not enter %HERE% & exit /b 1)

REM --- Python check -----------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not on PATH.
    echo Install Python 3.11 from https://www.python.org/downloads/ and
    echo tick "Add python.exe to PATH" during install.
    popd
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version') do set "PYVER=%%v"
echo Found %PYVER%

REM --- Virtual environment ---------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :fail
)

call ".venv\Scripts\activate.bat" || goto :fail

REM --- Dependencies -----------------------------------------------------
echo.
echo Installing dependencies. First run downloads ~2GB and may take 5-15 min.
python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt || goto :fail

REM --- Desktop folders --------------------------------------------------
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%\Sales Calls - Inbox"            mkdir "%DESKTOP%\Sales Calls - Inbox"
if not exist "%DESKTOP%\Sales Calls - Inbox\Processed"  mkdir "%DESKTOP%\Sales Calls - Inbox\Processed"
if not exist "%DESKTOP%\Sales Calls - Transcripts"      mkdir "%DESKTOP%\Sales Calls - Transcripts"
echo Created desktop folders.

REM --- Pre-download Whisper model --------------------------------------
echo.
echo Downloading Whisper large-v3 model (~3GB, one-time)...
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16')" || (
    echo.
    echo WARNING: Model preload failed. This usually means CUDA isn't set up.
    echo The service will still install, but transcription won't work until
    echo the rep installs an NVIDIA GPU driver and a CUDA-capable card is present.
)

REM --- Task Scheduler auto-start ---------------------------------------
echo.
echo Registering auto-start task...
set "TASKNAME=Sales Call Transcriber"
set "PYTHONW=%HERE%.venv\Scripts\pythonw.exe"
set "SCRIPT=%HERE%transcribe.py"
schtasks /Create /SC ONLOGON /TN "%TASKNAME%" /TR "\"%PYTHONW%\" \"%SCRIPT%\"" /RL LIMITED /F >nul || (
    echo WARNING: Could not register auto-start task. You can still run
    echo run.bat manually each time.
)

echo.
echo ==========================================
echo  Done.
echo ==========================================
echo.
echo - Service will auto-start at next Windows login.
echo - To start it now: double-click run.bat
echo - To check it's working: drop an MP3 into
echo     %DESKTOP%\Sales Calls - Inbox
echo - Transcripts appear in:
echo     %DESKTOP%\Sales Calls - Transcripts
echo.
popd
pause
exit /b 0

:fail
echo.
echo Setup failed. See messages above.
popd
pause
exit /b 1
