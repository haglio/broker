from __future__ import annotations

import logging
import threading
import time
from enum import StrEnum
from pathlib import Path

from app_support import broker_heartbeat
from app_support.file_channel import publish_stamp, publish_whole


class BrokerMode(StrEnum):
    CONTROL = "0"
    AUTO = "1"


def write_mode(path: Path, mode: BrokerMode, logger: logging.Logger, *,
               publish=publish_whole) -> None:
    if not publish(path, str(mode)):
        logger.error("Failed to write mode file %s", path)


_ATTEMPTS_PER_BEAT = 40
_DELAY_WHILE_HELD_S = 0.01


def heartbeat_loop(
    path: Path, stop_event: threading.Event, logger: logging.Logger,
    *, connected: threading.Event, sleep=time.sleep, clock=time.monotonic, publish=publish_stamp,
) -> None:
    last_landed, said_stopped = None, False
    while not stop_event.is_set():
        if not connected.is_set():
            last_landed, said_stopped = None, False
        elif publish(path, attempts=_ATTEMPTS_PER_BEAT, delay_s=_DELAY_WHILE_HELD_S):
            if said_stopped:
                logger.info("Broker heartbeat %s lands again", path)
            last_landed, said_stopped = clock(), False
        else:
            last_landed = clock() if last_landed is None else last_landed
            if not said_stopped and clock() - last_landed > broker_heartbeat.FRESH_S:
                logger.error("Broker heartbeat %s has not landed for %.1fs, so the apps reading it count the broker "
                             "as stopped", path, clock() - last_landed)
                said_stopped = True
        sleep(0.5)
