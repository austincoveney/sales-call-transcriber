"""Sales Call Transcriber - watches an inbox folder, transcribes audio,
writes plain-text transcripts to an output folder.

Supports three backends, selected at setup time and recorded in config.json:
    cuda           - faster-whisper on NVIDIA GPU (large-v3, float16)
    directcompute  - Const-me/Whisper CLI on AMD / Intel GPU via DirectX 11
    cpu            - faster-whisper on CPU (medium, int8)
"""

from __future__ import annotations

import ctypes
import datetime
import json
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
import winreg
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOG_DIR = SCRIPT_DIR / "logs"

APP_NAME = "Sales Call Transcriber"
MUTEX_NAME = "Local\\SalesCallTranscriberSingleInstance"
ERROR_ALREADY_EXISTS = 183

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".ogg", ".flac", ".aac", ".wma"}
LANGUAGE = "en"

# File stability + cloud-sync waits.
STABILITY_POLL_INTERVAL = 1.0
STABILITY_REQUIRED_SECONDS = 3.0
STABILITY_MAX_WAIT_SECONDS = 600.0   # cap so a cloud-only file doesn't hang forever
STABILITY_ZERO_BYTE_TIMEOUT = 10.0   # fail fast if size stays at 0

# Startup + periodic rescan to catch any dropped watchdog events.
STARTUP_SCAN_DELAY = 2.0
RESCAN_INTERVAL_SECONDS = 60.0

# Heartbeat: log every N seconds when idle so user can verify service is alive.
HEARTBEAT_INTERVAL_SECONDS = 600.0   # 10 min

# Subprocess timeout for directcompute backend only - we can SIGKILL the
# Const-me/Whisper child if it hangs. For in-process backends
# (faster-whisper) we can't safely kill a Python thread, so we don't try
# to time it out at all: a stuck inference would just block the worker
# until restart, which the user can do via stop.bat + run.bat.
# Per-second-of-audio multiplier is generous: even CPU mode on a slow
# machine rarely exceeds 2-3x real-time.
SUBPROCESS_TIMEOUT_PER_AUDIO_SECOND = 30.0
SUBPROCESS_TIMEOUT_BASE = 120.0          # 2 min base regardless
SUBPROCESS_TIMEOUT_MAX = 12 * 60 * 60.0  # cap at 12 hours

# Periodic "I'm still working" log so a slow transcription doesn't look
# hung in the log.
TRANSCRIBE_PROGRESS_INTERVAL = 60.0

# Pre-flight validation thresholds.
MIN_AUDIO_BYTES = 1024              # below this is almost certainly corrupt / empty
MAX_AUDIO_MB_WARNING = 500          # warn but still attempt

# Windows file attribute flags for OneDrive cloud-only files.
# A cloud-only file has FILE_ATTRIBUTE_OFFLINE or FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS set.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

# Module-level so the OS releases the mutex when the process exits.
_single_instance_handle: int | None = None


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def get_desktop_path() -> Path:
    """Return the user's real Desktop folder, including any OneDrive
    redirection. Falls back to %USERPROFILE%\\Desktop if the registry
    lookup fails."""
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
            if value:
                return Path(value)
    except OSError:
        pass
    return Path(os.environ["USERPROFILE"]) / "Desktop"


DESKTOP = get_desktop_path()
INBOX = DESKTOP / "Sales Calls - Inbox"
TRANSCRIPTS = DESKTOP / "Sales Calls - Transcripts"
PROCESSING = INBOX / "Processing"
PROCESSED = INBOX / "Processed"
FAILED = INBOX / "Failed"


def ensure_folders() -> None:
    for folder in (INBOX, TRANSCRIPTS, PROCESSING, PROCESSED, FAILED, LOG_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def recover_stranded_processing() -> None:
    """If a previous run died mid-transcription, files would be left in
    Processing/. Move them back to Inbox so they get retried."""
    if not PROCESSING.exists():
        return
    for path in PROCESSING.iterdir():
        if not path.is_file():
            continue
        target = unique_path(INBOX / path.name)
        try:
            shutil.move(str(path), str(target))
            log.info("Recovered stranded file from Processing: %s", path.name)
        except Exception as exc:
            log.warning("Could not recover %s: %s", path.name, exc)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTS


def is_cloud_only(path: Path) -> bool:
    """Return True if the file is a OneDrive 'cloud-only' placeholder
    (i.e. you'd need to download it to read its content)."""
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF:   # INVALID_FILE_ATTRIBUTES
            return False
        return bool(attrs & (
            FILE_ATTRIBUTE_OFFLINE
            | FILE_ATTRIBUTE_RECALL_ON_OPEN
            | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
        ))
    except Exception:
        return False


def trigger_cloud_download(path: Path) -> None:
    """Touch the file in a way that asks Windows / OneDrive to materialise
    the actual content locally. Reading 1 byte is enough."""
    try:
        with open(path, "rb") as f:
            f.read(1)
    except Exception:
        pass


def unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    parent = base.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------

def acquire_single_instance() -> bool:
    """Claim a named mutex so only one instance runs per session."""
    global _single_instance_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _single_instance_handle = handle
    return True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "transcribe.log"

    handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    if sys.stdout and sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(console)

    return logger


log = setup_logging()


# Cached so we don't pay the import cost on every toast.
_Notification = None


def toast(title: str, message: str) -> None:
    """Show a Windows toast notification."""
    global _Notification
    try:
        if _Notification is None:
            from winotify import Notification as _N
            _Notification = _N
        _Notification(app_id=APP_NAME, title=title, msg=message, duration="short").show()
    except Exception as exc:
        log.warning("Toast failed: %s", exc)


# ---------------------------------------------------------------------------
# Backend configuration
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Read config.json. Falls back to a cuda default for backwards
    compatibility with installs that predate the multi-backend support."""
    if not CONFIG_PATH.exists():
        log.warning("config.json missing; assuming cuda backend (legacy default)")
        return {"backend": "cuda"}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log.exception("Could not parse config.json: %s", exc)
        return {"backend": "cuda"}


def _register_cuda_dlls() -> None:
    """Add pip-installed NVIDIA bin directories to the Windows DLL search
    path so CTranslate2 can load cuBLAS / cuDNN at inference time."""
    if sys.platform != "win32":
        return
    nvidia_root = SCRIPT_DIR / ".venv" / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.exists():
        return
    for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
        bin_dir = nvidia_root / sub / "bin"
        if not bin_dir.exists():
            continue
        try:
            os.add_dll_directory(str(bin_dir))
        except OSError:
            pass
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------
# Each factory returns a tuple (transcribe_fn, describe_str). transcribe_fn
# takes a Path to an audio file and returns (text, audio_duration_seconds).

TranscribeFn = Callable[[Path], tuple[str, float]]


def _make_faster_whisper_backend(device: str, compute_type: str, model_size: str) -> tuple[TranscribeFn, str]:
    if device == "cuda":
        _register_cuda_dlls()

    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(audio_path: Path) -> tuple[str, float]:
        segments, info = model.transcribe(
            str(audio_path),
            language=LANGUAGE,
            vad_filter=True,
            beam_size=5,
        )
        parts = [seg.text.strip() for seg in segments]
        text = " ".join(p for p in parts if p).strip()
        return text, float(info.duration)

    return transcribe, f"faster-whisper ({model_size}, {device}, {compute_type})"


def _convert_to_wav(audio_path: Path, wav_path: Path) -> None:
    """Decode any supported audio file to 16 kHz mono PCM s16 WAV using PyAV.
    Const-me/Whisper requires this exact format."""
    import av  # lazy import

    container = av.open(str(audio_path))
    try:
        in_stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)

            for frame in container.decode(in_stream):
                for resampled in resampler.resample(frame):
                    wf.writeframes(resampled.to_ndarray().tobytes())
            # Flush
            for resampled in resampler.resample(None):
                wf.writeframes(resampled.to_ndarray().tobytes())
    finally:
        container.close()


def _make_directcompute_backend(model_path: Path, exe_path: Path, gpu_hint: str | None) -> tuple[TranscribeFn, str]:
    if not exe_path.exists():
        raise FileNotFoundError(f"Const-me/Whisper CLI not found at {exe_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"ggml model not found at {model_path}")

    def transcribe(audio_path: Path) -> tuple[str, float]:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            wav_path = tmp / "audio.wav"

            _convert_to_wav(audio_path, wav_path)

            duration = wav_path.stat().st_size / (16000 * 2)  # 16 kHz, s16 mono

            cmd = [
                str(exe_path),
                "-m", str(model_path),
                "-l", LANGUAGE,
                "-nt",          # no timestamps
                "-otxt",        # write <wav>.txt next to input
                "-nc",          # no ANSI colours
                "-f", str(wav_path),
            ]
            if gpu_hint:
                cmd += ["-gpu", gpu_hint]

            # Subprocess can be cleanly killed if it hangs, so we do
            # apply a (generous) timeout here.
            timeout = max(
                SUBPROCESS_TIMEOUT_BASE,
                min(SUBPROCESS_TIMEOUT_MAX, duration * SUBPROCESS_TIMEOUT_PER_AUDIO_SECOND),
            )

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=tmpdir,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Const-me/Whisper hit {int(timeout)}s timeout on a "
                    f"{duration:.0f}s audio file"
                ) from exc

            if result.returncode != 0:
                raise RuntimeError(
                    f"Const-me/Whisper exited {result.returncode}: "
                    f"{(result.stderr or result.stdout or '').strip()[:500]}"
                )

            # main.exe writes "<input>.txt" alongside the WAV
            txt_path = wav_path.with_suffix(wav_path.suffix + ".txt")
            if txt_path.exists():
                text = txt_path.read_text(encoding="utf-8").strip()
            else:
                text = result.stdout.strip()

            return text, duration

    desc = f"Const-me/Whisper ({model_path.name}, DirectCompute"
    if gpu_hint:
        desc += f", gpu={gpu_hint!r}"
    desc += ")"
    return transcribe, desc


def create_transcriber(config: dict) -> tuple[TranscribeFn, str]:
    """Build the configured transcriber. Raises if config is invalid or
    required files are missing."""
    backend = config.get("backend", "cuda")

    if backend == "cuda":
        return _make_faster_whisper_backend(
            device="cuda",
            compute_type=config.get("compute_type", "float16"),
            model_size=config.get("model_size", "large-v3"),
        )

    if backend == "cpu":
        return _make_faster_whisper_backend(
            device="cpu",
            compute_type=config.get("compute_type", "int8"),
            model_size=config.get("model_size", "medium"),
        )

    if backend == "directcompute":
        model_path = Path(config.get("model_path") or (SCRIPT_DIR / "models" / "ggml-large-v3.bin"))
        exe_path = Path(config.get("exe_path") or (SCRIPT_DIR / "bin" / "main.exe"))
        return _make_directcompute_backend(
            model_path=model_path,
            exe_path=exe_path,
            gpu_hint=config.get("gpu_hint"),
        )

    raise ValueError(f"Unknown backend in config.json: {backend!r}")


# ---------------------------------------------------------------------------
# Watch-folder pipeline
# ---------------------------------------------------------------------------

def wait_until_stable(path: Path, stop_event: threading.Event) -> tuple[bool, str | None]:
    """Block until file size stops changing.

    Returns (ok, reason). ok=False means we gave up; reason is a human
    string suitable for an error file (None if ok=True). Three caps stop
    us hanging forever:
      - hard cap STABILITY_MAX_WAIT_SECONDS (default 10 min)
      - early bail if size stayed at 0 for STABILITY_ZERO_BYTE_TIMEOUT
      - early bail if file disappears mid-wait
    """
    start = time.monotonic()
    last_size = -1
    stable_since: float | None = None
    zero_since: float | None = None

    while not stop_event.is_set():
        if time.monotonic() - start > STABILITY_MAX_WAIT_SECONDS:
            return False, (
                f"Gave up waiting for file to settle after "
                f"{STABILITY_MAX_WAIT_SECONDS:.0f}s. The file may be a "
                f"OneDrive cloud-only placeholder that didn't download, "
                f"or it's still being written by another program."
            )

        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False, "File disappeared from inbox before we could read it"

        # If OneDrive flagged it as cloud-only, ask Windows to fetch the
        # real content. Reading 1 byte is enough to start the download.
        if is_cloud_only(path):
            trigger_cloud_download(path)
            stable_since = None
            zero_since = None
            last_size = size
            time.sleep(STABILITY_POLL_INTERVAL)
            continue

        now = time.monotonic()

        if size == 0:
            # Track how long the file has been empty.
            if zero_since is None:
                zero_since = now
            elif now - zero_since >= STABILITY_ZERO_BYTE_TIMEOUT:
                return False, (
                    f"File has been 0 bytes for {STABILITY_ZERO_BYTE_TIMEOUT:.0f}s. "
                    f"Most likely it's empty / corrupted / a stub that wasn't "
                    f"actually written."
                )
            last_size = 0
            stable_since = None
        elif size == last_size:
            zero_since = None
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= STABILITY_REQUIRED_SECONDS:
                return True, None
        else:
            stable_since = None
            zero_since = None
            last_size = size

        time.sleep(STABILITY_POLL_INTERVAL)

    return False, "Service was shutting down"


def preflight(path: Path) -> str | None:
    """Cheap validation before we hand the file to a backend. Return None if
    OK, or a human reason string if the file should be rejected."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return f"Cannot read file metadata: {exc}"
    if size < MIN_AUDIO_BYTES:
        return f"File is too small to be valid audio ({size} bytes)"
    return None


def _build_error_report(
    exc: BaseException, *, backend: str, original_name: str, size_mb: float
) -> str:
    """Write a richer .error.txt than just the exception string. Caller is
    responsible for snapshotting size_mb before any move operations - by
    the time we get here the file may have moved to Failed/."""
    when = datetime.datetime.now().isoformat(timespec="seconds")
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return (
        f"Sales Call Transcriber error report\n"
        f"------------------------------------\n"
        f"When:        {when}\n"
        f"File:        {original_name}\n"
        f"Size:        {size_mb:.2f} MB\n"
        f"Backend:     {backend}\n"
        f"Error class: {type(exc).__name__}\n"
        f"Error:       {exc}\n"
        f"\n"
        f"Traceback:\n{tb}"
    )


def transcribe_one(transcribe_fn: TranscribeFn, audio: Path, *, backend: str) -> float:
    """Move audio through Processing -> Processed and return the captured
    size in MB so the caller can put it in error reports if needed."""
    # Capture size BEFORE moving so error reports get a real number even
    # if the file ends up in Failed/.
    size_mb = audio.stat().st_size / (1024 * 1024)

    # Move to Processing/ first so the user can see the inbox is empty
    # (work picked up) and the file is mid-flight.
    working = unique_path(PROCESSING / audio.name)
    shutil.move(str(audio), str(working))

    log.info("Transcribing %s (%.1f MB)", working.name, size_mb)
    if size_mb > MAX_AUDIO_MB_WARNING:
        log.warning("File is large (%.0f MB) - transcription will take a while", size_mb)
    toast("Transcribing", f"{working.name} ({size_mb:.1f} MB)")
    start = time.monotonic()

    # Run the backend on a worker thread so the main worker can log a
    # periodic "still running" line. We deliberately do NOT enforce a
    # timeout: faster-whisper runs in-process and can't be safely killed
    # by Python. A pathological hang means the user restarts the service,
    # at which point the stranded Processing/ file gets recovered.
    result_q: queue.Queue = queue.Queue(maxsize=1)
    stop_progress = threading.Event()

    def runner() -> None:
        try:
            result_q.put(("ok", transcribe_fn(working)))
        except BaseException as e:   # noqa: BLE001 - we want everything
            result_q.put(("err", e))

    def progress_logger() -> None:
        while not stop_progress.is_set():
            if stop_progress.wait(TRANSCRIBE_PROGRESS_INTERVAL):
                return
            elapsed_so_far = time.monotonic() - start
            log.info(
                "Still transcribing %s (%.0fs elapsed so far)",
                working.name, elapsed_so_far,
            )

    t = threading.Thread(target=runner, daemon=True, name=f"backend-{working.name}")
    t.start()
    progress = threading.Thread(target=progress_logger, daemon=True, name="progress")
    progress.start()

    try:
        status, payload = result_q.get()  # no timeout - trust the backend
    finally:
        stop_progress.set()

    if status == "err":
        try:
            shutil.move(str(working), str(unique_path(FAILED / working.name)))
        except Exception:
            log.exception("Could not move %s to Failed", working.name)
        raise payload   # re-raise the backend exception

    text, audio_duration = payload

    if not text:
        try:
            shutil.move(str(working), str(unique_path(FAILED / working.name)))
        except Exception:
            log.exception("Could not move empty-transcript %s to Failed", working.name)
        raise RuntimeError(
            "Backend returned an empty transcript. The audio may be silent, "
            "all noise, or in a language other than English."
        )

    out_path = unique_path(TRANSCRIPTS / f"{working.stem}.txt")
    out_path.write_text(text + "\n", encoding="utf-8")

    final = unique_path(PROCESSED / working.name)
    shutil.move(str(working), str(final))

    elapsed = time.monotonic() - start
    log.info(
        "Done %s in %.1fs (audio %.1fs, ratio %.1fx real-time)",
        working.name, elapsed, audio_duration,
        (audio_duration / elapsed) if elapsed > 0 else 0.0,
    )
    toast("Transcript ready", out_path.name)
    return size_mb


def write_error_file(audio_stem: str, body: str) -> None:
    err_path = unique_path(TRANSCRIPTS / f"{audio_stem}.error.txt")
    err_path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Dispatcher (de-duplicates between watchdog events and rescan)
# ---------------------------------------------------------------------------

class Dispatcher:
    """Owns the work queue and a set of in-flight / queued paths so the
    same file never gets enqueued twice (whether watchdog double-fires or
    the periodic rescan picks up a file that watchdog already saw)."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Path] = queue.Queue()
        self._known: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, path: Path, *, source: str) -> bool:
        """Returns True if enqueued, False if already known."""
        if not is_supported(path):
            return False
        if path.parent.resolve() != INBOX.resolve():
            return False
        key = str(path.resolve()).lower()
        with self._lock:
            if key in self._known:
                return False
            self._known.add(key)
        log.info("Queued from %s: %s", source, path.name)
        self._queue.put(path)
        return True

    def pop(self, timeout: float) -> Path | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def done(self, path: Path) -> None:
        key = str(path.resolve()).lower()
        with self._lock:
            self._known.discard(key)
        self._queue.task_done()

    def depth(self) -> int:
        return self._queue.qsize()


def worker_loop(
    transcribe_fn: TranscribeFn,
    backend_name: str,
    dispatcher: Dispatcher,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        audio = dispatcher.pop(timeout=1.0)
        if audio is None:
            continue
        original_name = audio.name
        original_size_mb = 0.0
        try:
            if not audio.exists():
                continue

            stable_ok, reason = wait_until_stable(audio, stop_event)
            if not stable_ok:
                if stop_event.is_set():
                    return
                log.warning("Skipping %s: %s", audio.name, reason)
                # Snapshot size while file may still exist.
                try:
                    original_size_mb = audio.stat().st_size / (1024 * 1024)
                except Exception:
                    pass
                write_error_file(audio.stem, _build_error_report(
                    RuntimeError(reason or "file did not stabilise"),
                    backend=backend_name,
                    original_name=original_name,
                    size_mb=original_size_mb,
                ))
                try:
                    if audio.exists():
                        shutil.move(str(audio), str(unique_path(FAILED / audio.name)))
                except Exception:
                    log.exception("Could not move unstable %s to Failed", audio.name)
                toast("Transcription failed", audio.name)
                continue

            try:
                original_size_mb = audio.stat().st_size / (1024 * 1024)
            except Exception:
                pass

            reject = preflight(audio)
            if reject:
                log.warning("Rejecting %s: %s", audio.name, reject)
                write_error_file(audio.stem, _build_error_report(
                    RuntimeError(reject),
                    backend=backend_name,
                    original_name=original_name,
                    size_mb=original_size_mb,
                ))
                try:
                    shutil.move(str(audio), str(unique_path(FAILED / audio.name)))
                except Exception:
                    log.exception("Could not move rejected %s to Failed", audio.name)
                toast("Transcription failed", audio.name)
                continue

            transcribe_one(transcribe_fn, audio, backend=backend_name)

        except Exception as exc:
            log.exception("Failed to transcribe %s", original_name)
            try:
                write_error_file(Path(original_name).stem, _build_error_report(
                    exc,
                    backend=backend_name,
                    original_name=original_name,
                    size_mb=original_size_mb,
                ))
                toast("Transcription failed", original_name)
            except Exception:
                log.exception("Failed to write error file for %s", original_name)
        finally:
            dispatcher.done(audio)


def rescan_loop(dispatcher: Dispatcher, stop_event: threading.Event) -> None:
    """Periodically sweep the Inbox in case watchdog missed an event.
    Cheap: just iterdir and try to enqueue (dispatcher de-dupes)."""
    while not stop_event.is_set():
        # Wait first so we don't double-up with the startup scan.
        if stop_event.wait(RESCAN_INTERVAL_SECONDS):
            return
        try:
            for path in INBOX.iterdir():
                if path.is_file() and is_supported(path):
                    dispatcher.submit(path, source="rescan")
        except Exception:
            log.exception("Rescan failed")


def heartbeat_loop(dispatcher: Dispatcher, stop_event: threading.Event) -> None:
    """Periodic 'I'm alive' log line so the user can see in logs.bat that
    the service is healthy even when idle."""
    while not stop_event.is_set():
        if stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            return
        log.info("Heartbeat: idle, queue depth %d", dispatcher.depth())


def scan_existing(dispatcher: Dispatcher) -> None:
    for path in INBOX.iterdir():
        if path.is_file() and is_supported(path):
            dispatcher.submit(path, source="startup-scan")


def main() -> int:
    ensure_folders()
    log.info("=" * 50)
    log.info("Starting %s", APP_NAME)

    if not acquire_single_instance():
        log.info("Another instance is already running; exiting.")
        logging.shutdown()
        os._exit(0)

    log.info("Inbox:       %s", INBOX)
    log.info("Transcripts: %s", TRANSCRIPTS)

    recover_stranded_processing()

    config = load_config()
    backend = config.get("backend", "cuda")
    log.info("Backend: %s", backend)

    try:
        transcribe_fn, describe = create_transcriber(config)
    except Exception as exc:
        log.exception("Failed to initialise backend")
        toast("Transcriber failed to start", str(exc))
        return 1
    log.info("Loaded: %s", describe)

    # Lazy import watchdog so the doomed mutex instance doesn't drag it in.
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    dispatcher = Dispatcher()
    stop_event = threading.Event()

    class InboxHandler(FileSystemEventHandler):
        def on_created(self, event) -> None:
            if not event.is_directory:
                dispatcher.submit(Path(event.src_path), source="watchdog/created")

        def on_moved(self, event) -> None:
            if not event.is_directory:
                dispatcher.submit(Path(event.dest_path), source="watchdog/moved")

    worker = threading.Thread(
        target=worker_loop,
        args=(transcribe_fn, backend, dispatcher, stop_event),
        daemon=True,
        name="transcribe-worker",
    )
    worker.start()

    rescan_thread = threading.Thread(
        target=rescan_loop,
        args=(dispatcher, stop_event),
        daemon=True,
        name="rescan",
    )
    rescan_thread.start()

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(dispatcher, stop_event),
        daemon=True,
        name="heartbeat",
    )
    heartbeat_thread.start()

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX), recursive=False)
    observer.start()
    log.info("Watching inbox (watchdog + periodic rescan every %ds)", int(RESCAN_INTERVAL_SECONDS))

    time.sleep(STARTUP_SCAN_DELAY)
    scan_existing(dispatcher)

    def shutdown(signum, frame) -> None:
        log.info("Shutdown requested (signal %s)", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        observer.stop()
        observer.join(timeout=5)
        worker.join(timeout=10)
        rescan_thread.join(timeout=5)
        heartbeat_thread.join(timeout=5)
        log.info("Stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
