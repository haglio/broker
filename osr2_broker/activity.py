from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import publish_stamp


class ActivityStamp:
    WRITE_INTERVAL_SECONDS = 5.0

    def __init__(self, path: Path, *, wall_clock: Callable[[], float] = time.time,
                 publish: Callable[[Path, float], object] = publish_stamp):
        self._path = path
        self._wall_clock = wall_clock
        self._publish = publish
        self._marked = 0.0
        self._last_write = 0.0

    def mark(self) -> None:
        self._marked = self._wall_clock()

    def publish_what_was_marked(self) -> None:
        marked = self._marked
        if marked - self._last_write < self.WRITE_INTERVAL_SECONDS:
            return
        self._last_write = marked
        self._publish(self._path, marked)
