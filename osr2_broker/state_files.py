"""The files the broker publishes itself through.

Four small files under the shared state directory, and the loop that keeps one
of them fresh. They are the only thing fun_time, genau, clipper and the tray see
of a running broker, so their contents are a wire format: the mode file holds
"0" or "1" and nothing else, and the heartbeat holds one wall-clock float.

Reading and writing are best-effort in both directions. A write happens on every
AUTO transition and twice a second for the heartbeat, from threads whose real
job is carrying serial traffic; a state directory that has gone away, or a file
another process is mid-replace on, must cost the update and never the bridge.
Reads default to the safe answer -- Genau enabled -- because the alternative is
a broker that silently stops publishing after a half-written file.

Writers on the other side of these files are often PowerShell, which leaves a
UTF-8 BOM, so every read strips one before looking at what it found.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

# Spelled as an escape, not as the character: written literally it is invisible
# in the source and indistinguishable from a stray space.
_BOM = "\ufeff"


def _stripped_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace(_BOM, "").strip()


def _write_best_effort(path: Path, text: str, logger: logging.Logger, failure: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except Exception:
        logger.exception(failure, path)


def write_mode(path: Path, value: str, logger: logging.Logger) -> None:
    _write_best_effort(path, value, logger, "Failed to write mode file %s")


def write_heartbeat(path: Path, logger: logging.Logger) -> None:
    _write_best_effort(path, str(time.time()), logger, "Failed to write broker heartbeat %s")


def read_genau_enabled(path: Path) -> bool:
    try:
        if not path.exists():
            return True
        return _stripped_text(path) != "0"
    except Exception:
        return True


def ensure_genau_enabled_file(path: Path, logger: logging.Logger) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or not _stripped_text(path):
            path.write_text("1", encoding="utf-8")
    except Exception:
        logger.exception("Failed to initialize Genau enabled file %s", path)


def heartbeat_loop(
    path: Path, stop_event: threading.Event, logger: logging.Logger,
    *, connected: threading.Event, sleep=time.sleep,
) -> None:
    while not stop_event.is_set():
        if connected.is_set():
            write_heartbeat(path, logger)
        sleep(0.5)
