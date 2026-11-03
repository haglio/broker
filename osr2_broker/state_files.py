from __future__ import annotations

import logging
import threading
import time
from enum import StrEnum
from pathlib import Path

from app_support.file_channel import publish_stamp, publish_whole


class BrokerMode(StrEnum):
    CONTROL = "0"
    AUTO = "1"


def write_mode(path: Path, mode: BrokerMode, logger: logging.Logger) -> None:
    if not publish_whole(path, str(mode)):
        logger.error("Failed to write mode file %s", path)


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
