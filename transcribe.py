"""Sales Call Transcriber - watches an inbox folder, transcribes audio,
writes plain-text transcripts to an output folder.

Supports three backends, selected at setup time and recorded in config.json:
    cuda           - faster-whisper on NVIDIA GPU (large-v3, float16)
    directcompute  - Const-me/Whisper CLI on AMD / Intel GPU via DirectX 11
    cpu            - faster-whisper on CPU (medium, int8)
"""

from __future__ import annotations

import ctypes
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

STABILITY_POLL_INTERVAL = 1.0
STABILITY_REQUIRED_SECONDS = 3.0
STARTUP_SCAN_DELAY = 2.0

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


def toast(title: str, message: str) -> None:
    """Show a Windows toast notification. Lazy-imports winotify so the
    doomed second instance doesn't pay the import cost."""
    try:
        from winotify import Notification
        Notification(app_id=APP_NAME, title=title, msg=message, duration="short").show()
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

            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=tmpdir
            )
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

def wait_until_stable(path: Path, stop_event: threading.Event) -> bool:
    last_size = -1
    stable_since: float | None = None
    while not stop_event.is_set():
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        now = time.monotonic()
        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= STABILITY_REQUIRED_SECONDS:
                return True
        else:
            stable_since = None
            last_size = size
        time.sleep(STABILITY_POLL_INTERVAL)
    return False


def transcribe_one(transcribe_fn: TranscribeFn, audio: Path) -> None:
    # Move to Processing/ first so the user can see the inbox is empty
    # (work picked up) and the file is mid-flight.
    working = unique_path(PROCESSING / audio.name)
    shutil.move(str(audio), str(working))

    size_mb = working.stat().st_size / (1024 * 1024)
    log.info("Transcribing %s (%.1f MB)", working.name, size_mb)
    toast("Transcribing", f"{working.name} ({size_mb:.1f} MB)")
    start = time.monotonic()

    try:
        text, audio_duration = transcribe_fn(working)
    except Exception:
        # Move to Failed/ - don't return to Inbox, that'd cause an
        # infinite retry loop via watchdog's on_moved event.
        try:
            shutil.move(str(working), str(unique_path(FAILED / working.name)))
        except Exception:
            log.exception("Could not move %s to Failed", working.name)
        raise

    if not text:
        raise RuntimeError("Backend returned an empty transcript")

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


def write_error_file(audio: Path, reason: str) -> None:
    err_path = unique_path(TRANSCRIPTS / f"{audio.stem}.error.txt")
    err_path.write_text(reason + "\n", encoding="utf-8")


def worker_loop(transcribe_fn: TranscribeFn, work_queue: queue.Queue, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            audio: Path = work_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            if not audio.exists():
                continue
            if not wait_until_stable(audio, stop_event):
                continue
            transcribe_one(transcribe_fn, audio)
        except Exception as exc:
            log.exception("Failed to transcribe %s", audio)
            try:
                write_error_file(audio, f"{type(exc).__name__}: {exc}")
                toast("Transcription failed", audio.name)
            except Exception:
                log.exception("Failed to write error file for %s", audio)
        finally:
            work_queue.task_done()


def scan_existing(work_queue: queue.Queue) -> None:
    for path in INBOX.iterdir():
        if path.is_file() and is_supported(path):
            log.info("Queuing leftover file from inbox: %s", path.name)
            work_queue.put(path)


def main() -> int:
    ensure_folders()
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

    work_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    class InboxHandler(FileSystemEventHandler):
        def _enqueue(self, raw_path: str) -> None:
            path = Path(raw_path)
            if path.parent.resolve() != INBOX.resolve():
                return
            if not is_supported(path):
                return
            log.info("Detected new file: %s", path.name)
            work_queue.put(path)

        def on_created(self, event) -> None:
            if not event.is_directory:
                self._enqueue(event.src_path)

        def on_moved(self, event) -> None:
            if not event.is_directory:
                self._enqueue(event.dest_path)

    worker = threading.Thread(
        target=worker_loop,
        args=(transcribe_fn, work_queue, stop_event),
        daemon=True,
        name="transcribe-worker",
    )
    worker.start()

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX), recursive=False)
    observer.start()
    log.info("Watching inbox")

    time.sleep(STARTUP_SCAN_DELAY)
    scan_existing(work_queue)

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
        log.info("Stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
