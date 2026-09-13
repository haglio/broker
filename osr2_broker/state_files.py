"""The files the broker publishes itself through.

Three small files under the shared state directory, and the loop that keeps one
of them fresh. They are the only thing fun_time, genau, clipper and the tray see
of a running broker, so their contents are a wire format: the mode file holds
"0" or "1" and nothing else, and the heartbeat holds one wall-clock float.  The
names are the family's (``app_support.state_files``), and the reading and the
writing are ``app_support.file_channel``'s, which is what the other side of
every one of these files reads and writes with.

Writing is best-effort. A write happens on every AUTO transition and twice a
second for the heartbeat, from threads whose real job is carrying serial
traffic; a state directory that has gone away, or a file another process is
mid-replace on, must cost the update and never the bridge.
"""
from __future__ import annotations

import logging
import threading
import time
from enum import StrEnum
from pathlib import Path

from app_support import state_files
from app_support.file_channel import publish_stamp, publish_whole


class BrokerMode(StrEnum):
    """What the broker is doing with the OSR2, as its mode file spells it: holding
    the device under Fun Time's control, or running it itself in auto."""

    CONTROL = "0"
    AUTO = "1"

    @property
    def label(self) -> str:
        return "control" if self is BrokerMode.CONTROL else "auto"


def write_mode(path: Path, mode: BrokerMode, logger: logging.Logger) -> None:
    """Published whole: the orchestrator polls this, and a poller that caught a
    truncating write would read a blank it cannot tell from "controlled"."""
    if not publish_whole(path, str(mode)):
        logger.error("Failed to write mode file %s", path)


# What the mode file was called while it was named after Genau, which never read it.
_LAST_SESSIONS_MODE_FILE = "genau_mode.txt"


def rename_last_sessions_mode_file(state_dir: Path, logger: logging.Logger) -> bool:
    """Move the mode file a broker of last session's left to today's name, once,
    where the broker starts; one already under today's name wins and the old one
    goes.  Returns whether it renamed."""
    old, new = state_dir / _LAST_SESSIONS_MODE_FILE, state_dir / state_files.BROKER_MODE
    try:
        if not old.exists():
            return False
        if new.exists():
            old.unlink()
            return False
        old.replace(new)
    except OSError:
        logger.exception("Could not rename %s to %s", old, new)
        return False
    return True


def write_heartbeat(path: Path, logger: logging.Logger) -> None:
    if not publish_stamp(path):
        logger.error("Failed to write broker heartbeat %s", path)


def heartbeat_loop(
    path: Path, stop_event: threading.Event, logger: logging.Logger,
    *, connected: threading.Event, sleep=time.sleep,
) -> None:
    while not stop_event.is_set():
        if connected.is_set():
            write_heartbeat(path, logger)
        sleep(0.5)
