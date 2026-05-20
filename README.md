# Sales Call Transcriber

A silent Windows background service. Drop sales call MP3s in a desktop folder, plain-text transcripts appear in another. Runs locally on your PC using OpenAI's Whisper model on an NVIDIA GPU — no cloud, no per-minute fees, no audio leaves your machine.

Built for sales reps who record their calls and want to paste transcripts into ChatGPT/Claude for analysis (summary, objections, next steps, etc.).

---

## What it does

1. You drop any audio file into `Desktop\Sales Calls - Inbox\`
2. The service notices, transcribes it on your GPU (~30-90 seconds for a 10-minute call)
3. A `.txt` transcript appears in `Desktop\Sales Calls - Transcripts\`
4. The original audio is moved into `Sales Calls - Inbox\Processed\`
5. A Windows toast notification confirms it's ready

The transcript is plain text — just the spoken words. Paste it into Claude or ChatGPT to identify speakers, summarise, pull objections, etc.

**Supported formats:** `.mp3`, `.m4a`, `.wav`, `.mp4`, `.ogg`, `.flac`, `.aac`, `.wma`

---

## Requirements

- **Windows 10 or 11**
- **NVIDIA GPU** with recent drivers (RTX 20-series or newer recommended)
- About **5 GB of free disk space** (for dependencies + the Whisper model)
- An internet connection for the one-time install

You do **not** need Python, Git, or any developer tooling — `setup.bat` installs Python automatically if it's missing.

If you don't have an NVIDIA GPU, this won't work — open an issue or ask the maintainer about a CPU-only build.

---

## Install (first time, ~15-20 minutes)

### Step 1 — Download

1. Go to **https://github.com/austincoveney/sales-call-transcriber**
2. Click the green **Code** button → **Download ZIP**
3. Open the downloaded zip. You'll see a folder called `sales-call-transcriber-main`
4. Extract that folder **anywhere you like** — Downloads, Documents, `C:\Tools\`, your desktop, it doesn't matter. The tool is self-contained and works from any location.
5. Rename it from `sales-call-transcriber-main` to `sales-call-transcriber` if you want (optional, just neater)

**One thing to avoid:** don't extract it inside a OneDrive-synced folder (like `OneDrive\Documents`). The Python environment is ~3 GB and OneDrive will try to upload it. Plain `Downloads\` or `C:\Tools\` is ideal.

### Step 2 — Update your NVIDIA driver (skip if you're already on a recent driver)

1. Go to **https://www.nvidia.com/Download/index.aspx**
2. Pick your GPU model from the dropdowns and download the latest driver
3. Run the installer, accept defaults

If you're not sure what GPU you have: press <kbd>Win</kbd>+<kbd>R</kbd>, type `dxdiag`, press Enter, click the **Display** tab, look at the **Name** field.

### Step 3 — Run setup.bat

1. Open the extracted folder in File Explorer
2. **Double-click `setup.bat`**
3. A black window appears and starts working. **Leave it alone** — this takes 5 to 20 minutes the first time. It will:
   - Check for an NVIDIA GPU (warns if missing)
   - Install Python 3.12 automatically if you don't have Python (uses winget if available, otherwise downloads the official installer from python.org)
   - Create a Python environment inside the folder
   - Download ~2 GB of dependencies
   - Download the ~3 GB Whisper speech recognition model
   - Create the desktop folders
   - Register the service to auto-start when you log in
4. When you see `Done.` and `Press any key to continue...`, press any key.

If anything fails, the window stays open with the error message. Copy it and send it to whoever set this up for you.

**If `setup.bat` tells you to restart and re-run it:** that means Python was just installed and needs Windows to refresh the PATH. Close the window, reopen it, double-click `setup.bat` again. It'll skip everything that's already done and finish quickly.

### Step 4 — Start it

Two options:

- **Easiest:** restart your PC. The service auto-starts on login.
- **Or:** double-click `run.bat` to start it immediately.

Either way, the service runs silently in the background from now on. You won't see a window — that's correct.

### Step 5 — Test it

1. Find any MP3 file (or record a 30-second voice memo)
2. Drag it into `Desktop\Sales Calls - Inbox`
3. Wait 30 seconds to 2 minutes
4. A Windows toast notification appears: **"Transcript ready: yourfile.txt"**
5. Open `Desktop\Sales Calls - Transcripts\yourfile.txt` — it'll contain the spoken words

If nothing happens after 2-3 minutes, double-click `status.bat` to check the service is running, and `logs.bat` to see what it's doing.

---

## Daily usage

There is no UI. The service is always on once installed. Just:

1. Record / save your call audio as MP3 (or any supported format)
2. Drop it into `Desktop\Sales Calls - Inbox`
3. Wait for the toast notification
4. Open the transcript in `Desktop\Sales Calls - Transcripts`
5. Copy-paste it into Claude / ChatGPT with a prompt like:

   > Here's a transcript of a sales call. Identify the rep and prospect, summarise key points, list objections raised, and suggest next steps.

The original MP3 lives in `Sales Calls - Inbox\Processed\` afterward if you need it again. Clear that folder periodically — it'll fill up.

---

## Helper scripts

All inside the folder where you extracted the tool:

| Script         | What it does |
|----------------|---|
| `setup.bat`    | First-time install. Safe to re-run any time (idempotent). |
| `run.bat`      | Manually start the service. (Normally auto-starts on login.) |
| `stop.bat`     | Stop the service. |
| `status.bat`   | Check whether the service is running. |
| `logs.bat`     | Open the log file in Notepad. |

---

## Moving the folder later

You can move the install folder anywhere after the fact — but the Windows auto-start task points at the old location, so it won't run on login until you re-register it.

To fix this after moving:

1. Open the folder in its new location
2. Double-click `setup.bat`
3. It'll skip everything that's already installed and just re-register the auto-start task with the new path. Takes about 30 seconds.

---

## Troubleshooting

**The black window from `run.bat` flashes and closes immediately.**
That's correct. The service runs hidden in the background — there's no visible window. Run `status.bat` to confirm it's running.

**Nothing happens when I drop an MP3.**
1. Run `status.bat`. If it says `NOT RUNNING`, double-click `run.bat`.
2. If it says `RUNNING`, run `logs.bat` and look at the most recent lines — copy them to whoever set this up for you.
3. Check the file actually landed in `Sales Calls - Inbox` and not `Sales Calls - Inbox\Processed`.

**An `.error.txt` file appears instead of a transcript.**
Open it — it explains what went wrong. Common causes:
- Audio file is corrupted or zero bytes
- GPU ran out of memory (close other GPU-heavy apps and try again)
- Format isn't actually audio (e.g. a renamed `.txt`)
- NVIDIA driver too old (see **Step 2** above)

**`setup.bat` failed at the Python install step.**
It should have shown one of two messages:
- "Could not download Python installer" → check internet connection, retry, or install Python 3.12 manually from https://www.python.org/downloads/ then re-run `setup.bat`
- "Python installed but is not visible in this session yet" → close the window, open a new Command Prompt, re-run `setup.bat`

**The service doesn't start when I log in.**
Open Windows Task Scheduler (search for it in Start), find **Sales Call Transcriber** in the list, right-click → Run. If that works, right-click → Properties → Triggers and verify "At log on" is set. If it doesn't work, re-run `setup.bat` from the install folder to re-register.

**Transcripts are wrong language / missing accuracy.**
The model assumes English. If your calls are in another language, the maintainer can change the `LANGUAGE` setting at the top of `transcribe.py` to e.g. `"es"`, `"fr"`, or remove it entirely for auto-detection.

**Where do I find logs?**
`logs\transcribe.log` inside your install folder — or just double-click `logs.bat`. The log rotates automatically (keeps the last 3 files, each up to 2 MB).

---

## Uninstalling

1. Run `stop.bat`
2. Open Task Scheduler, delete the **Sales Call Transcriber** task
3. Delete the install folder
4. Optionally delete the desktop folders (`Sales Calls - Inbox` and `Sales Calls - Transcripts`)
5. Optionally delete the downloaded Whisper model from `C:\Users\<you>\.cache\huggingface\`
6. Optionally uninstall Python (Settings → Apps → Python 3.12) if `setup.bat` installed it for you and you don't need it for anything else

---

## Updating to a new version

If a new version of this tool is released:

1. Run `stop.bat`
2. Re-download the zip from GitHub (Step 1 above) and replace the files in your install folder — **keep your `.venv` and `logs` folders, don't overwrite them**
3. Double-click `setup.bat`. It'll detect the existing venv, upgrade any changed dependencies, and re-register the auto-start task. Fast.
4. Run `run.bat`

---

## How it works (for the curious)

- **faster-whisper** runs OpenAI's Whisper `large-v3` speech recognition model on your GPU via CTranslate2. About 10× faster than the official Python implementation.
- **watchdog** watches the Inbox folder for new files using Windows file system events (no polling).
- A single worker thread pulls from a queue and transcribes one file at a time. Files are checked for size stability before processing (so partially-copied files aren't picked up).
- A named Windows mutex (`Local\SalesCallTranscriberSingleInstance`) prevents multiple instances stacking up if `run.bat` is clicked more than once.
- The script registers the NVIDIA cuBLAS / cuDNN DLL directories on the Windows search path at startup, so the pip-installed `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` packages work without a system-wide CUDA install.
- Logs go to `logs/transcribe.log`, rotating at 2 MB.
- Auto-start uses Windows Task Scheduler (`schtasks /SC ONLOGON`) with an absolute path to the install folder.
- All paths are resolved from `Path(__file__).parent` and `%~dp0`, so the tool works from any location.

Everything runs locally. No audio or transcript ever leaves your PC.
