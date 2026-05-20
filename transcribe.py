"""Sales Call Transcriber — watches an inbox folder, transcribes audio with
faster-whisper, writes plain-text transcripts to an output folder."""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import shutil
import signal
import sys
import threading
import time
import winreg
from logging.handlers import RotatingFileHandler
from pathlib import Path

from faster_whisper import WhisperModel
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from winotify import Notification


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


SCRIPT_DIR = Path(__file__).resolve().parent
DESKTOP = get_desktop_path()

INBOX = DESKTOP / "Sales Calls - Inbox"
TRANSCRIPTS = DESKTOP / "Sales Calls - Transcripts"
PROCESSED = INBOX / "Processed"
LOG_DIR = SCRIPT_DIR / "logs"

MODEL_SIZE = "large-v3"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"
LANGUAGE = "en"

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".ogg", ".flac", ".aac", ".wma"}

STABILITY_POLL_INTERVAL = 1.0
STABILITY_REQUIRED_SECONDS = 3.0
STARTUP_SCAN_DELAY = 2.0

APP_NAME = "Sales Call Transcriber"
MUTEX_NAME = "Local\\SalesCallTranscriberSingleInstance"
ERROR_ALREADY_EXISTS = 183

# Module-level so the OS releases the mutex when the process exits.
_single_instance_handle: int | None = None


def acquire_single_instance() -> bool:
    """Try to claim a named mutex so only one instance runs per session.
    Returns False if another instance already holds the mutex."""
    global _single_instance_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True  # If the API fails, don't block startup.
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _single_instance_handle = handle
    return True


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "transcribe.log"

    handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    if sys.stdout and sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(console)

    return logger


log = setup_logging()


def toast(title: str, message: str) -> None:
    try:
        Notification(
            app_id=APP_NAME, title=title, msg=message, duration="short"
        ).show()
    except Exception as exc:
        log.warning("Toast failed: %s", exc)


def ensure_folders() -> None:
    for folder in (INBOX, TRANSCRIPTS, PROCESSED, LOG_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTS


def wait_until_stable(path: Path, stop_event: threading.Event) -> bool:
    """Block until file size stops changing. Returns False if file vanishes
    or shutdown is requested."""
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


def transcribe_one(model: WhisperModel, audio: Path) -> None:
    log.info("Transcribing %s", audio.name)
    start = time.monotonic()

    segments, info = model.transcribe(
        str(audio),
        language=LANGUAGE,
        vad_filter=True,
        beam_size=5,
    )

    text_parts: list[str] = []
    for segment in segments:
        text_parts.append(segment.text.strip())

    transcript = " ".join(p for p in text_parts if p).strip()

    if not transcript:
        raise RuntimeError("Whisper returned an empty transcript")

    out_path = unique_path(TRANSCRIPTS / f"{audio.stem}.txt")
    out_path.write_text(transcript + "\n", encoding="utf-8")

    target = unique_path(PROCESSED / audio.name)
    shutil.move(str(audio), str(target))

    elapsed = time.monotonic() - start
    log.info(
        "Done %s in %.1fs (audio %.1fs, lang=%s)",
        audio.name,
        elapsed,
        info.duration,
        info.language,
    )
    toast("Transcript ready", out_path.name)


def write_error_file(audio: Path, reason: str) -> None:
    err_path = unique_path(TRANSCRIPTS / f"{audio.stem}.error.txt")
    err_path.write_text(reason + "\n", encoding="utf-8")


class InboxHandler(FileSystemEventHandler):
    def __init__(self, work_queue: queue.Queue[Path]) -> None:
        super().__init__()
        self.queue = work_queue

    def _enqueue(self, raw_path: str) -> None:
        path = Path(raw_path)
        if path.parent.resolve() != INBOX.resolve():
            return
        if not is_supported(path):
            return
        log.info("Detected new file: %s", path.name)
        self.queue.put(path)

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._enqueue(event.src_path)

    def on_moved(self, event) -> None:
        if event.is_directory:
            return
        self._enqueue(event.dest_path)


def worker_loop(
    model: WhisperModel,
    work_queue: queue.Queue[Path],
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        try:
            audio = work_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            if not audio.exists():
                continue

            if not wait_until_stable(audio, stop_event):
                continue

            transcribe_one(model, audio)
        except Exception as exc:
            log.exception("Failed to transcribe %s", audio)
            try:
                write_error_file(audio, f"{type(exc).__name__}: {exc}")
                toast("Transcription failed", audio.name)
            except Exception:
                log.exception("Failed to write error file for %s", audio)
        finally:
            work_queue.task_done()


def scan_existing(work_queue: queue.Queue[Path]) -> None:
    for path in INBOX.iterdir():
        if path.is_file() and is_supported(path):
            log.info("Queuing leftover file from inbox: %s", path.name)
            work_queue.put(path)


def main() -> int:
    ensure_folders()
    log.info("Starting %s", APP_NAME)

    if not acquire_single_instance():
        log.info("Another instance is already running; exiting.")
        return 0

    log.info("Inbox:       %s", INBOX)
    log.info("Transcripts: %s", TRANSCRIPTS)

    log.info("Loading Whisper model %s on %s (%s)…", MODEL_SIZE, DEVICE, COMPUTE_TYPE)
    try:
        model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    except Exception as exc:
        log.exception("Failed to load Whisper model")
        toast("Transcriber failed to start", str(exc))
        return 1
    log.info("Model loaded")

    work_queue: queue.Queue[Path] = queue.Queue()
    stop_event = threading.Event()

    worker = threading.Thread(
        target=worker_loop,
        args=(model, work_queue, stop_event),
        daemon=True,
        name="transcribe-worker",
    )
    worker.start()

    handler = InboxHandler(work_queue)
    observer = Observer()
    observer.schedule(handler, str(INBOX), recursive=False)
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
