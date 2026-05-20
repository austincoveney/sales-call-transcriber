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
- **Python 3.11** (the installer walks you through this if you don't have it)
- About **5 GB of free disk space** (for dependencies + the Whisper model)

If you don't have an NVIDIA GPU, this won't work — open an issue or ask the maintainer about a CPU-only build.

---

## Full install (first time, ~20 minutes)

Follow these in order. Most of the time is waiting for downloads to finish.

### Step 1 — Install Python 3.11

Skip this if you already have Python 3.11 installed.

1. Go to **https://www.python.org/downloads/release/python-3119/**
2. Scroll to the bottom of the page, under **Files**
3. Click **Windows installer (64-bit)** to download the `.exe`
4. Run the installer
5. **CRITICAL:** On the first screen, before clicking Install, **tick the box that says "Add python.exe to PATH"** at the bottom. If you miss this, the rest of the setup won't work.
6. Click **Install Now**
7. When it finishes, click **Close**

To verify it worked: press <kbd>Win</kbd>+<kbd>R</kbd>, type `cmd`, press Enter. In the black window, type `python --version` and press Enter. You should see something like `Python 3.11.9`. Close the window.

### Step 2 — Update your NVIDIA driver

1. Go to **https://www.nvidia.com/Download/index.aspx**
2. Pick your GPU model from the dropdowns and download the latest driver
3. Run the installer, accept defaults, let it finish (it'll flicker your screen briefly)

If you're not sure what GPU you have: press <kbd>Win</kbd>+<kbd>R</kbd>, type `dxdiag`, press Enter, click the **Display** tab, look at the **Name** field.

### Step 3 — Download the transcriber code

1. Go to **https://github.com/austincoveney/sales-call-transcriber**
2. Click the green **Code** button (top right of the file list)
3. Click **Download ZIP**
4. Open the downloaded zip. You'll see a folder called `sales-call-transcriber-main` inside
5. Create a folder called `dev` on your **C:** drive (so the path is `C:\dev\`)
6. Drag the `sales-call-transcriber-main` folder from the zip into `C:\dev\`
7. Rename it from `sales-call-transcriber-main` to `sales-call-transcriber`

You should now have everything at `C:\dev\sales-call-transcriber\`.

### Step 4 — Run the installer

1. Open `C:\dev\sales-call-transcriber\` in File Explorer
2. **Double-click `setup.bat`**
3. A black window appears and starts printing text. **Leave it alone and let it work** — this takes 5 to 15 minutes the first time. It's:
   - Creating a Python environment
   - Downloading ~2 GB of dependencies
   - Downloading the ~3 GB Whisper speech recognition model
   - Creating the desktop folders
   - Registering the service to auto-start when you log in
4. When you see `Done.` and `Press any key to continue...`, press any key. The window closes.

If you see any **ERROR** or **WARNING** lines, copy them and send them to whoever set this up for you.

### Step 5 — Start it for the first time

You have two options:

- **Easiest:** restart your PC. The service will auto-start on login.
- **Or:** double-click `run.bat` to start it immediately.

Either way, the service runs silently in the background from now on. You won't see a window — that's correct.

### Step 6 — Test it

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

All inside `C:\dev\sales-call-transcriber\`:

| Script         | What it does |
|----------------|---|
| `setup.bat`    | First-time install. You only run this once. |
| `run.bat`      | Manually start the service. (Normally auto-starts on login.) |
| `stop.bat`     | Stop the service. |
| `status.bat`   | Check whether the service is running. |
| `logs.bat`     | Open the log file in Notepad — useful when something's wrong. |

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

**`setup.bat` failed with a CUDA error.**
Your NVIDIA driver is probably out of date. Redo **Step 2** above, then re-run `setup.bat`.

**`setup.bat` failed with `python is not recognised`.**
You missed the "Add python.exe to PATH" checkbox in **Step 1**. Uninstall Python from Settings → Apps, then redo Step 1 carefully.

**The service doesn't start when I log in.**
Open Windows Task Scheduler (search for it in Start), find **Sales Call Transcriber** in the list, right-click → Run. If that works, right-click → Properties → Triggers and verify "At log on" is set.

**Transcripts are wrong language / missing accuracy.**
The model assumes English. If your calls are in another language, the maintainer can change the `LANGUAGE` setting at the top of `transcribe.py` to e.g. `"es"`, `"fr"`, or remove it entirely for auto-detection.

**Where do I find logs?**
`C:\dev\sales-call-transcriber\logs\transcribe.log` — or just double-click `logs.bat`. The log rotates automatically (keeps the last 3 files, each up to 2 MB).

---

## Uninstalling

1. Run `stop.bat`
2. Open Task Scheduler, delete the **Sales Call Transcriber** task
3. Delete the `C:\dev\sales-call-transcriber\` folder
4. Optionally delete the desktop folders (`Sales Calls - Inbox` and `Sales Calls - Transcripts`)
5. Optionally delete the downloaded Whisper model from `C:\Users\<you>\.cache\huggingface\`

---

## Updating to a new version

If a new version of this tool is released:

1. Run `stop.bat`
2. Re-download the zip from GitHub (Step 3 above) and replace the files in `C:\dev\sales-call-transcriber\` (keep your `.venv` and `logs` folders)
3. Open a Command Prompt in `C:\dev\sales-call-transcriber\` and run:
   ```
   .venv\Scripts\pip install -r requirements.txt --upgrade
   ```
4. Run `run.bat`

---

## How it works (for the curious)

- **faster-whisper** runs OpenAI's Whisper `large-v3` speech recognition model on your GPU via CTranslate2. About 10× faster than the official Python implementation.
- **watchdog** watches the Inbox folder for new files using Windows file system events (no polling).
- A single worker thread pulls from a queue and transcribes one file at a time. Files are checked for size stability before processing (so partially-copied files aren't picked up).
- A named Windows mutex (`Local\SalesCallTranscriberSingleInstance`) prevents multiple instances stacking up.
- Logs go to `logs/transcribe.log`, rotating at 2 MB.
- Auto-start uses Windows Task Scheduler (`schtasks /SC ONLOGON`).

Everything runs locally. No audio or transcript ever leaves your PC.
