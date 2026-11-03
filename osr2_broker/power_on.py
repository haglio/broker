from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import stamp_age


class PowerOnWatch:
    SILENCE_SECONDS = 60.0

    def __init__(
        self,
        *,
        rx_stamp_file: Path,
        monotonic: Callable[[], float],
        wall_clock: Callable[[], float] = time.time,
    ):
        self._monotonic = monotonic
        age = stamp_age(rx_stamp_file, wall_clock())
        self._silent_before_this_run = age is None or age >= self.SILENCE_SECONDS
        self._last_rx: float | None = None

    def rx_broke_the_silence(self) -> bool:
        now = self._monotonic()
        previous, self._last_rx = self._last_rx, now
        if previous is None:
            return self._silent_before_this_run
        return now - previous >= self.SILENCE_SECONDS
