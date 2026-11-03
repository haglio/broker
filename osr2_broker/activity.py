from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import publish_stamp


class ActivityStamp:
    WRITE_INTERVAL_SECONDS = 5.0

    def __init__(self, path: Path, *, wall_clock: Callable[[], float] = time.time):
        self._path = path
        self._wall_clock = wall_clock
        self._last_write = 0.0

    def mark(self) -> None:
        now = self._wall_clock()
        if now - self._last_write < self.WRITE_INTERVAL_SECONDS:
            return
        self._last_write = now
        publish_stamp(self._path, now)
