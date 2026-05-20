# Sales Call Transcriber - status report.
# Invoked by status.bat. Surfaces service state, backend, queue depth,
# in-flight file, last completed transcription, and recent errors.

$ErrorActionPreference = 'Continue'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $here 'config.json'
$logPath = Join-Path $here 'logs\transcribe.log'

# Resolve the real Desktop (OneDrive-aware) the same way transcribe.py does.
$desktop = [Environment]::GetFolderPath('Desktop')
$inbox = Join-Path $desktop 'Sales Calls - Inbox'
$processing = Join-Path $inbox 'Processing'
$processed = Join-Path $inbox 'Processed'
$failed = Join-Path $inbox 'Failed'
$transcripts = Join-Path $desktop 'Sales Calls - Transcripts'

function Get-FolderCount([string]$path) {
    if (-not (Test-Path $path)) { return 0 }
    return (Get-ChildItem -Path $path -File -ErrorAction SilentlyContinue).Count
}

function Get-FolderNames([string]$path, [int]$limit = 5) {
    if (-not (Test-Path $path)) { return @() }
    return Get-ChildItem -Path $path -File -ErrorAction SilentlyContinue | Select-Object -First $limit -ExpandProperty Name
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Sales Call Transcriber - Status" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Service running?
$procs = Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*transcribe.py*' }

if ($procs) {
    $main = $procs | Sort-Object CreationDate | Select-Object -First 1
    $ageMin = [int]((New-TimeSpan -Start $main.CreationDate -End (Get-Date)).TotalMinutes)
    Write-Host ("Service:     " ) -NoNewline
    Write-Host "RUNNING" -ForegroundColor Green -NoNewline
    Write-Host ("  (up {0} min, PID {1})" -f $ageMin, $main.ProcessId)
} else {
    Write-Host ("Service:     " ) -NoNewline
    Write-Host "NOT RUNNING" -ForegroundColor Red
    Write-Host "             Double-click run.bat to start it."
}

# Backend from config.json
if (Test-Path $configPath) {
    try {
        $raw = Get-Content -Raw $configPath
        # Strip BOM if present
        if ($raw[0] -eq [char]0xFEFF) { $raw = $raw.Substring(1) }
        $config = $raw | ConvertFrom-Json
        Write-Host ("Backend:     " + $config.backend)
        if ($config.model_size) { Write-Host ("Model:       " + $config.model_size) }
    } catch {
        Write-Host "Backend:     UNKNOWN (config.json malformed)" -ForegroundColor Yellow
    }
} else {
    Write-Host "Backend:     UNKNOWN (config.json missing)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Folder state:"
Write-Host ("  Inbox (queued):     {0,4} file(s)" -f (Get-FolderCount $inbox))
Write-Host ("  Processing (now):   {0,4} file(s)" -f (Get-FolderCount $processing))
Write-Host ("  Processed (done):   {0,4} file(s)" -f (Get-FolderCount $processed))

$failedCount = Get-FolderCount $failed
if ($failedCount -gt 0) {
    Write-Host ("  Failed:             {0,4} file(s)" -f $failedCount) -ForegroundColor Yellow
} else {
    Write-Host ("  Failed:             {0,4} file(s)" -f $failedCount)
}

# Show the file currently being transcribed
$processingFiles = Get-FolderNames $processing 1
if ($processingFiles) {
    Write-Host ""
    Write-Host ("Currently transcribing: " + $processingFiles[0]) -ForegroundColor Cyan
}

# Show queued files
$queuedFiles = Get-FolderNames $inbox 5
if ($queuedFiles) {
    Write-Host ""
    Write-Host "Queued:"
    foreach ($f in $queuedFiles) { Write-Host ("  - " + $f) }
    $extra = (Get-FolderCount $inbox) - $queuedFiles.Count
    if ($extra -gt 0) { Write-Host ("  ... and {0} more" -f $extra) }
}

# Recent activity from the log
if (Test-Path $logPath) {
    $recentLog = Get-Content -Path $logPath -Tail 200 -ErrorAction SilentlyContinue
    $lastDone = $recentLog | Where-Object { $_ -match 'Done\s+' } | Select-Object -Last 1
    $lastHeartbeat = $recentLog | Where-Object { $_ -match 'Heartbeat' } | Select-Object -Last 1
    $lastError = $recentLog | Where-Object { $_ -match '\[ERROR\]' } | Select-Object -Last 1

    Write-Host ""
    Write-Host "Recent activity:"
    if ($lastDone) {
        Write-Host ("  Last completed:  " + $lastDone.Trim()) -ForegroundColor Green
    } else {
        Write-Host "  Last completed:  (no transcriptions yet)"
    }
    if ($lastHeartbeat) {
        Write-Host ("  Last heartbeat:  " + $lastHeartbeat.Trim())
    }
    if ($lastError) {
        Write-Host ("  Last error:      " + $lastError.Trim()) -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "Log file not yet created (service hasn't started?)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Helpers: run.bat | stop.bat | logs.bat" -ForegroundColor DarkGray
