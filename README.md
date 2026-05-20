# Sales Call Transcriber

Background Windows service. Drop MP3s in a folder, plain-text transcripts appear in another. Runs locally on the rep's PC using faster-whisper large-v3 on an NVIDIA GPU.

## What it does

- Watches `Desktop\Sales Calls - Inbox\` for new audio files
- Transcribes them with faster-whisper large-v3 (GPU)
- Writes plain `.txt` to `Desktop\Sales Calls - Transcripts\`
- Moves the processed audio into `Desktop\Sales Calls - Inbox\Processed\`
- Pops a Windows toast when each transcript is ready
- Auto-starts on Windows login

Output is just the spoken words — no speaker labels, no timestamps. Paste the `.txt` into Claude to get speakers, summary, objections, next steps.

Supported formats: `.mp3`, `.m4a`, `.wav`, `.mp4`, `.ogg`, `.flac`, `.aac`, `.wma`.

## Requirements (on the rep's PC)

- Windows 10/11
- NVIDIA GPU with up-to-date drivers (RTX 20-series or newer recommended)
- Python 3.11, added to PATH

## Install

1. Clone or copy this folder to `C:\dev\sales-call-transcriber\`.
2. Double-click `setup.bat`. Wait for it to finish (5-15 min on first run — downloads dependencies and the ~3GB Whisper model).
3. Either restart Windows or double-click `run.bat` to start the service now.

That's it. Drop an MP3 into `Desktop\Sales Calls - Inbox\` to test.

## Files

| File              | Purpose |
|-------------------|---------|
| `transcribe.py`   | The watch-folder service |
| `requirements.txt`| Python dependencies |
| `setup.bat`       | One-time installer (creates venv, installs deps, registers auto-start) |
| `run.bat`         | Start the service hidden (no console) |
| `stop.bat`        | Stop any running instance |
| `logs/`           | Rotating log of every transcription |

## Troubleshooting

**Nothing happens when I drop a file.**  Check `logs\transcribe.log`. If the service isn't running, double-click `run.bat`.

**`.error.txt` appeared instead of a transcript.**  Open it — it contains the failure reason. Common causes: corrupted MP3, GPU out of memory, model not downloaded.

**CUDA / GPU errors at startup.**  Update NVIDIA drivers from [nvidia.com](https://www.nvidia.com/Download/index.aspx). The pip-installed CUDA libs in the venv need a recent driver to work.

**Service won't auto-start.**  Open Task Scheduler, find `Sales Call Transcriber`, check Triggers = "At log on" and Actions points at `.venv\Scripts\pythonw.exe`.
