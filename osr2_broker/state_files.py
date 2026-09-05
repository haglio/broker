"""The files the broker publishes itself through.

Four small files under the shared state directory, and the loop that keeps one
of them fresh. They are the only thing fun_time, genau, clipper and the tray see
of a running broker, so their contents are a wire format: the mode file holds
"0" or "1" and nothing else, and the heartbeat holds one wall-clock float.  The
names are the family's (``app_support.state_files``), and the reading and the
writing are ``app_support.file_channel``'s, which is what the other side of
every one of these files reads and writes with.

Reading and writing are best-effort in both directions. A write happens on every
AUTO transition and twice a second for the heartbeat, from threads whose real
job is carrying serial traffic; a state directory that has gone away, or a file
another process is mid-replace on, must cost the update and never the bridge.
Reads default to the safe answer -- Genau enabled -- because the alternative is
a broker that silently stops publishing after a half-written file.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from app_support.file_channel import publish_stamp, publish_whole, read_flag

# Spelled as an escape, not as the character: written literally it is invisible
# in the source and indistinguishable from a stray space.  The writers on the
# other side of the enabled flag are often PowerShell, which leaves one.
_BOM = "﻿"


def _stripped_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace(_BOM, "").strip()


def write_mode(path: Path, value: str, logger: logging.Logger) -> None:
    """Published whole: the orchestrator polls this, and a poller that caught a
    truncating write would read a blank it cannot tell from "controlled"."""
    if not publish_whole(path, value):
        logger.error("Failed to write mode file %s", path)


def write_heartbeat(path: Path, logger: logging.Logger) -> None:
    if not publish_stamp(path):
        logger.error("Failed to write broker heartbeat %s", path)


def read_genau_enabled(path: Path) -> bool:
    """On until somebody turns it off: only a "0" is a decision."""
    return read_flag(path, default=True)


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
