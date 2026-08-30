"""When the OSR2 last spoke, and when it was last spoken to.

Two files, one per direction, each holding a single wall-clock stamp. The
monitor reads them to decide whether the device is powered on and whether it is
being driven, so the value on disk is a wall clock -- not the monotonic clock the
session times its own loops with.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable


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
        try:
            self._path.write_text(str(now), encoding="utf-8")
        except OSError:
            pass
