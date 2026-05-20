@echo off
setlocal enableextensions enabledelayedexpansion

echo ==========================================
echo  Sales Call Transcriber - Setup
echo ==========================================
echo Location: %~dp0
echo.

set "HERE=%~dp0"
pushd "%HERE%" || (echo Could not enter %HERE% & exit /b 1)

REM --- OneDrive sync warning -------------------------------------------
echo "%HERE%" | findstr /I "OneDrive" >nul
if not errorlevel 1 (
    echo NOTE: This folder is inside OneDrive. The Python environment
    echo ^(~3GB^) will be created here and OneDrive may try to sync it.
    echo Recommended: move to C:\Tools\ or your Downloads folder before
    echo continuing - press Ctrl+C now if you want to do that.
    echo.
    timeout /t 8 >nul
)

REM --- GPU detection ---------------------------------------------------
echo Detecting GPU...
powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name | Where-Object { $_ -and $_ -notmatch 'Microsoft Basic' } | ForEach-Object { Write-Host ('  - ' + $_) }"

REM Write backend choice to a temp file to avoid cmd's nightmarish escape rules.
set "BACKEND_FILE=%TEMP%\sct_backend.txt"
del "%BACKEND_FILE%" >nul 2>&1
powershell -NoProfile -Command "$n = (Get-CimInstance Win32_VideoController).Name -join ';'; $b = if ($n -match 'NVIDIA|GeForce|Quadro|Tesla') { 'cuda' } elseif ($n -match 'AMD|Radeon|Intel.*Arc|Intel.*Iris.*Xe') { 'directcompute' } else { 'cpu' }; Set-Content -NoNewline -Path $env:BACKEND_FILE -Value $b"

set "BACKEND="
if exist "%BACKEND_FILE%" set /p BACKEND=<"%BACKEND_FILE%"
del "%BACKEND_FILE%" >nul 2>&1

if not defined BACKEND (
    echo ERROR: Could not determine backend.
    popd
    pause
    exit /b 1
)

if /i "%BACKEND%"=="cuda" echo Backend: cuda  ^(NVIDIA GPU via CUDA, fastest^)
if /i "%BACKEND%"=="directcompute" echo Backend: directcompute  ^(AMD/Intel GPU via DirectX 11, near-GPU speed^)
if /i "%BACKEND%"=="cpu" echo Backend: cpu  ^(no compatible GPU detected, will be slow^)
echo.

REM --- Python check / auto-install -------------------------------------
set "PYTHON_CMD="
call :find_python
if defined PYTHON_CMD goto have_python

echo.
echo Python is not installed. Installing it automatically...
echo.

REM Try winget (preferred - Windows 10 1809+ / Windows 11)
where winget >nul 2>&1
if not errorlevel 1 (
    echo Installing Python 3.12 via winget...
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements --scope user
    REM winget returns non-zero if package was already installed; that's fine.
    call :refresh_path
    call :find_python
    if defined PYTHON_CMD goto have_python
)

REM Fall back to direct download from python.org
echo Downloading Python 3.12.7 installer from python.org...
set "PY_INSTALLER=%TEMP%\python-3.12.7-amd64.exe"
powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%PY_INSTALLER%' -UseBasicParsing; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo ERROR: Could not download Python installer. Check your internet
    echo connection, or install Python 3.12 manually from
    echo https://www.python.org/downloads/ then re-run this script.
    popd
    pause
    exit /b 1
)

echo Installing Python (user-mode, no admin needed)...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
set "PY_RC=%errorlevel%"
del "%PY_INSTALLER%" >nul 2>&1
if not "%PY_RC%"=="0" (
    echo ERROR: Python installer returned exit code %PY_RC%.
    popd
    pause
    exit /b 1
)

call :refresh_path
call :find_python
if defined PYTHON_CMD goto have_python

echo.
echo Python installed but is not visible in this session yet. Please:
echo   1. Close this window
echo   2. Open a NEW Command Prompt (or restart your PC)
echo   3. Double-click setup.bat again
echo.
popd
pause
exit /b 1

:have_python
echo Using Python: %PYTHON_CMD%

REM --- Virtual environment ---------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv .venv || goto :fail
)

call ".venv\Scripts\activate.bat" || goto :fail

REM --- Backend-specific dependencies -----------------------------------
echo.
echo Installing dependencies for backend: %BACKEND%
echo First-time install downloads ^~2GB and may take 5-15 min.
python -m pip install --upgrade pip || goto :fail
python -m pip install -r "requirements_%BACKEND%.txt" || goto :fail

REM --- DirectCompute extras: binary + model ----------------------------
if /i "%BACKEND%"=="directcompute" (
    echo.
    echo Downloading Const-me/Whisper CLI...
    if not exist "bin" mkdir "bin"
    set "CLI_ZIP=%TEMP%\const-me-cli.zip"
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://github.com/Const-me/Whisper/releases/download/1.12.0/cli.zip' -OutFile '!CLI_ZIP!' -UseBasicParsing; Expand-Archive -Force -Path '!CLI_ZIP!' -DestinationPath '%HERE%bin'; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
    if errorlevel 1 (
        echo ERROR: Failed to download Const-me/Whisper CLI.
        goto :fail
    )
    del "!CLI_ZIP!" >nul 2>&1
    echo CLI installed at %HERE%bin\main.exe

    echo.
    echo Downloading ggml-large-v3 model ^(~3.1GB, one-time^)...
    if not exist "models" mkdir "models"
    if not exist "models\ggml-large-v3.bin" (
        powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin' -OutFile '%HERE%models\ggml-large-v3.bin' -UseBasicParsing; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
        if errorlevel 1 (
            echo ERROR: Failed to download model.
            goto :fail
        )
    ) else (
        echo Model already present, skipping download.
    )
)

REM --- Write config.json -----------------------------------------------
echo.
echo Writing config.json...
powershell -NoProfile -Command "@{ backend = '%BACKEND%'; gpu_names = '%GPU_NAMES%'; setup_at = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'); install_dir = '%HERE%' } | ConvertTo-Json | Set-Content -Encoding UTF8 -Path 'config.json'"

REM --- Desktop folders (OneDrive-aware) --------------------------------
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
if "%DESKTOP%"=="" set "DESKTOP=%USERPROFILE%\Desktop"
echo Desktop resolved to: %DESKTOP%
if not exist "%DESKTOP%\Sales Calls - Inbox"            mkdir "%DESKTOP%\Sales Calls - Inbox"
if not exist "%DESKTOP%\Sales Calls - Inbox\Processed"  mkdir "%DESKTOP%\Sales Calls - Inbox\Processed"
if not exist "%DESKTOP%\Sales Calls - Transcripts"      mkdir "%DESKTOP%\Sales Calls - Transcripts"
echo Created desktop folders.

REM --- Pre-download Whisper model (CUDA/CPU only) ----------------------
if /i "%BACKEND%"=="cuda" (
    echo.
    echo Downloading Whisper large-v3 model ^(~3GB, one-time^)...
    python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16')" || echo WARNING: Model preload failed. Transcription won't work until CUDA is properly set up.
)
if /i "%BACKEND%"=="cpu" (
    echo.
    echo Downloading Whisper medium model ^(~1.5GB, one-time^)...
    python -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')" || echo WARNING: Model preload failed.
)

REM --- Task Scheduler auto-start ---------------------------------------
echo.
echo Registering auto-start task (will overwrite any previous entry)...
set "PYTHONW=%HERE%.venv\Scripts\pythonw.exe"
set "SCRIPT=%HERE%transcribe.py"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$action = New-ScheduledTaskAction -Execute '%PYTHONW%' -Argument '\"%SCRIPT%\"'; $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); try { Register-ScheduledTask -TaskName 'Sales Call Transcriber' -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null; exit 0 } catch { Write-Host ('schtasks error: ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 (
    echo WARNING: Could not register auto-start task. You can still run
    echo run.bat manually each time.
)

echo.
echo ==========================================
echo  Done.  Backend: %BACKEND%
echo ==========================================
echo.
echo - Service auto-starts at next Windows login.
echo - To start it now: double-click run.bat
echo - Drop MP3s into:
echo     %DESKTOP%\Sales Calls - Inbox
echo - Transcripts appear in:
echo     %DESKTOP%\Sales Calls - Transcripts
echo.
echo Helpers:
echo   run.bat     - start the service now (or after restart)
echo   stop.bat    - stop a running service
echo   status.bat  - check whether it's running
echo   logs.bat    - open the log file
echo.
echo NOTE: If you move this folder later, re-run setup.bat from the
echo new location to update the auto-start path.
echo.
popd
pause
exit /b 0


REM ======================================================================
REM Subroutines
REM ======================================================================

:find_python
REM Probes for a usable Python. Sets PYTHON_CMD if found.
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
        for /f "delims=" %%v in ('python --version 2^>^&1') do echo Found %%v
        exit /b 0
    )
)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
        for /f "delims=" %%v in ('py -3 --version 2^>^&1') do echo Found %%v via py launcher
        exit /b 0
    )
)
exit /b 1

:refresh_path
REM Re-reads the user PATH from the registry so a freshly installed
REM Python is visible in this cmd session without having to reopen it.
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USERPATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "MACHPATH=%%b"
if defined USERPATH set "PATH=%USERPATH%;%PATH%"
if defined MACHPATH set "PATH=%MACHPATH%;%PATH%"
exit /b 0


:fail
echo.
echo Setup failed. See messages above.
popd
pause
exit /b 1
