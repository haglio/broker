"""What a logger says, heard as it says it -- from whichever thread says it."""
from __future__ import annotations

import logging
import queue
import time
from collections.abc import Iterator
from contextlib import contextmanager


class Heard(logging.Handler):
    def __init__(self):
        super().__init__()
        self._lines = queue.Queue()

    def emit(self, record):
        self._lines.put(record.getMessage())

    def first_saying(self, words: str, *, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while True:
            line = self._lines.get(timeout=max(deadline - time.monotonic(), 0.0))
            if words in line:
                return line


@contextmanager
def what_is_said_on(logger_name: str) -> Iterator[Heard]:
    logger = logging.getLogger(logger_name)
    heard, level = Heard(), logger.level
    logger.addHandler(heard)
    logger.setLevel(logging.INFO)
    try:
        yield heard
    finally:
        logger.removeHandler(heard)
        logger.setLevel(level)
