# Sales Call Transcriber

A silent Windows background service. Drop sales call MP3s in a desktop folder, plain-text transcripts appear in another. Runs locally on your PC — no cloud, no per-minute fees, no audio leaves your machine.

Auto-detects your GPU and picks the best backend:

| GPU                          | Backend         | What it uses                                  | Speed (rough) |
|------------------------------|-----------------|-----------------------------------------------|----------------|
| NVIDIA (RTX 20-series+)      | `cuda`          | faster-whisper + CUDA, large-v3 model         | 4-10× real-time |
| AMD Radeon / Intel Arc       | `directcompute` | Const-me/Whisper + DirectX 11, large-v3 model | 2-5× real-time |
| No compatible GPU            | `cpu`           | faster-whisper CPU, medium int8 model         | 0.5-1× real-time |

Built for sales reps who record their calls and want to paste transcripts into ChatGPT/Claude for analysis (summary, objections, next steps, etc.).

---

## What it does

1. You drop any audio file into `Desktop\Sales Calls - Inbox\`
2. The service notices and immediately moves it into `Inbox\Processing\` so you can see it's been picked up. Toast: **"Transcribing yourfile.mp3 (12.4 MB)"**.
3. It transcribes on your GPU (or CPU)
4. A `.txt` transcript appears in `Desktop\Sales Calls - Transcripts\`
5. The original audio moves from `Processing\` to `Inbox\Processed\`. Toast: **"Transcript ready: yourfile.txt"**.

You can always tell what state things are in by glancing at the folders:

| Folder                       | Means                                                     |
|------------------------------|-----------------------------------------------------------|
| `Inbox\`                     | Files waiting to be transcribed (queued, not started)     |
| `Inbox\Processing\`          | The file currently being transcribed (max 1 at a time)    |
| `Inbox\Processed\`           | Successfully transcribed — keep, archive, or delete       |
| `Inbox\Failed\`              | Transcription failed — see paired `.error.txt` in Transcripts |
| `Transcripts\`               | The `.txt` outputs (and any `.error.txt` files)           |

The transcript is plain text — just the spoken words. Paste it into Claude or ChatGPT to identify speakers, summarise, pull objections, etc.

**Supported formats:** `.mp3`, `.m4a`, `.wav`, `.mp4`, `.ogg`, `.flac`, `.aac`, `.wma`

---

## Requirements

- **Windows 10 or 11**
- About **5 GB of free disk space** (for dependencies + the Whisper model). The DirectCompute backend needs an additional ~3 GB for its model.
- An internet connection for the one-time install
- For the **fastest** experience: an NVIDIA GPU (RTX 20-series or newer) with recent drivers. AMD Radeon (RX 5000+) and Intel Arc also work via the DirectCompute backend at slightly lower speeds. With no GPU, it falls back to CPU — works on anything but a 10-min call may take 10+ minutes to transcribe.

You do **not** need Python, Git, or any developer tooling — `setup.bat` installs Python automatically if it's missing.

---

## Install (first time, ~15-20 minutes)

### Step 1 — Download

1. Go to **https://github.com/austincoveney/sales-call-transcriber**
2. Click the green **Code** button → **Download ZIP**
3. Open the downloaded zip. You'll see a folder called `sales-call-transcriber-main`
4. Extract that folder **anywhere you like** — Downloads, Documents, `C:\Tools\`, your desktop, it doesn't matter. The tool is self-contained and works from any location.
5. Rename it from `sales-call-transcriber-main` to `sales-call-transcriber` if you want (optional, just neater)

**One thing to avoid:** don't extract it inside a OneDrive-synced folder (like `OneDrive\Documents`). The Python environment is ~3 GB and OneDrive will try to upload it. Plain `Downloads\` or `C:\Tools\` is ideal.

### Step 2 — Update your GPU driver (skip if you're already on a recent driver)

- **NVIDIA:** https://www.nvidia.com/Download/index.aspx — pick your model, download, install.
- **AMD:** https://www.amd.com/en/support — same idea.
- **Intel Arc:** https://www.intel.com/content/www/us/en/download-center/home.html

If you're not sure what GPU you have: press <kbd>Win</kbd>+<kbd>R</kbd>, type `dxdiag`, press Enter, click the **Display** tab, look at the **Name** field.

### Step 3 — Run setup.bat

1. Open the extracted folder in File Explorer
2. **Double-click `setup.bat`**
3. A black window appears and starts working. **Leave it alone** — this takes 5 to 20 minutes the first time. It will:
   - Detect your GPU and pick a backend (`cuda` / `directcompute` / `cpu`)
   - Install Python 3.12 automatically if you don't have Python (uses winget if available, otherwise downloads the official installer from python.org)
   - Create a Python environment inside the folder
   - Install backend-specific dependencies (~1-2 GB)
   - Download the Whisper model (~3 GB for `cuda` and `directcompute`, ~1.5 GB for `cpu`)
   - For the `directcompute` backend: also download the Const-me/Whisper CLI binary (small)
   - Write a `config.json` recording the chosen backend
   - Create the desktop folders
   - Register the service to auto-start when you log in
4. When you see `Done.  Backend: <name>` and `Press any key to continue...`, press any key.

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
| `status.bat`   | Detailed status: running? backend? queue depth? currently transcribing? last completed? last error? |
| `logs.bat`     | Open the log file in Notepad. |

`status.bat` is the one to use any time you're wondering whether things are working. It shows you exactly what state the service is in and what it's doing right now.

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
1. Wait. A 10-minute call takes 30 sec - 3 min on GPU, much longer on CPU. Look at `Inbox\Processing\` — if your file is in there, it's being worked on right now.
2. Run `status.bat`. If it says `NOT RUNNING`, double-click `run.bat`.
3. If it says `RUNNING` but the file's been sitting in `Inbox\` for ages, run `logs.bat` and look at the most recent lines — copy them to whoever set this up for you.
4. Check the file actually landed in `Inbox\` and not `Inbox\Processed\` (already done) or `Inbox\Processing\` (in progress).

**Transcription seems slow.**
The service shares your GPU with other apps. Close GPU-heavy programs (games, Chrome/Firefox with many tabs, video editors, streaming software) and try again. The log file records a "ratio Nx real-time" line — anything above 2x is healthy.

**A file ended up in `Inbox\Failed\`.**
Look in `Transcripts\` for a matching `<name>.error.txt` — it explains why. To retry, drag the file from `Failed\` back into `Inbox\`. Common causes: corrupted audio, unsupported codec, GPU out of memory.

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

## Reliability features

The service is built to keep working without supervision. In particular:

- **Periodic Inbox rescan** every 60 seconds catches any files that the Windows file-system watcher missed (which can happen under heavy I/O).
- **De-duplication** — even if the same file is detected by both the watcher and the rescan, it'll only be queued once.
- **Pre-flight validation** rejects 0-byte and obviously corrupt files within ~10 seconds rather than waiting for the transcription backend to fail later.
- **OneDrive cloud-only detection** — if a file shows up in the Inbox as a cloud placeholder (i.e. you'd need to download it), the service triggers the download and waits for it to materialise. Hard cap of 10 minutes so it doesn't wait forever.
- **Stranded-file recovery** — if the service is killed mid-transcription (Windows reboot, crash, manual stop), the file is left in `Inbox\Processing\`. On the next start, it gets moved back to `Inbox\` and retried.
- **Single-instance lock** — clicking `run.bat` multiple times won't stack up multiple service instances; the duplicate exits immediately.
- **Structured error reports** — every failed file produces a `.error.txt` with timestamp, file name, size, backend, error class, error message, and full Python traceback.
- **Progress logging** — long transcriptions log a "still working" line every 60 seconds so the log doesn't look frozen.
- **Heartbeat** — every 10 minutes when idle, the service logs `Heartbeat: idle, queue depth N`. If you can't see recent heartbeats, the service has hung.
- **Auto-start on login** via Task Scheduler — survives reboots.
- **Subprocess timeout** for the DirectCompute backend (Const-me/Whisper). The in-process faster-whisper backends don't have a timeout because Python threads can't be safely killed; instead, a stuck transcription is recoverable by stopping the service and starting it again.

## How it works (for the curious)

**Backend selection** — `setup.bat` queries `Win32_VideoController` via WMI to find every GPU, then picks:

- `cuda` if any GPU name matches NVIDIA / GeForce / Quadro / Tesla
- `directcompute` if any matches AMD / Radeon / Intel Arc / Intel Iris Xe
- `cpu` otherwise

The choice is written to `config.json`. `transcribe.py` reads it on startup and dispatches to the right backend implementation.

**The three backends:**

- **`cuda`** uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — a CTranslate2 port of OpenAI's Whisper that runs the `large-v3` model on NVIDIA GPUs. ~10× faster than the reference implementation. We register the pip-installed cuBLAS / cuDNN DLL directories on the Windows search path at startup so it works without a system-wide CUDA install.
- **`directcompute`** uses [Const-me/Whisper](https://github.com/Const-me/Whisper) — a high-performance DirectX 11 / DirectCompute port of Whisper that runs on any modern Windows GPU (AMD, Intel, NVIDIA). We shell out to its `main.exe` after converting input audio to 16 kHz mono WAV with PyAV.
- **`cpu`** uses faster-whisper in CPU mode with the smaller `medium` model and `int8` quantisation. Slower but works on any hardware.

**Watch-folder pipeline:**

- **watchdog** watches the Inbox folder for new files using Windows file system events (no polling).
- A single worker thread pulls from a queue and transcribes one file at a time. Files are checked for size stability before processing so partially-copied files aren't picked up.
- A named Windows mutex (`Local\SalesCallTranscriberSingleInstance`) prevents multiple instances stacking up if `run.bat` is clicked more than once.
- Logs go to `logs/transcribe.log`, rotating at 2 MB.
- Auto-start uses Windows Task Scheduler (`Register-ScheduledTask`) with an absolute path to the install folder.
- All paths are resolved from `Path(__file__).parent` and `%~dp0`, so the tool works from any location.

**Overriding the backend** — edit `config.json` manually if auto-detection picks wrong, or if you want to force a specific model. Valid keys:

```json
{
    "backend": "cuda | directcompute | cpu",
    "model_size": "tiny | base | small | medium | large-v3",
    "compute_type": "int8 | int8_float16 | float16 | float32",
    "model_path": "absolute path to ggml-*.bin (directcompute only)",
    "exe_path": "absolute path to Const-me/Whisper main.exe (directcompute only)",
    "gpu_hint": "GPU adapter name to force (directcompute only, e.g. 'AMD Radeon RX 7900 XT')"
}
```

Restart the service after editing (`stop.bat` then `run.bat`).

Everything runs locally. No audio or transcript ever leaves your PC.
