from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import publish_stamp


class NotAnsweringWatch:
    DRIVEN_S = 180.0
    FORGOTTEN_AFTER_S = 600.0
    RENEWED_EVERY_S = 1.0

    def __init__(self, *, stamp_file: Path, monotonic: Callable[[], float],
                 logger: logging.Logger) -> None:
        self._stamp_file = stamp_file
        self._monotonic = monotonic
        self._logger = logger
        self._driven = 0.0
        self._last_tick: float | None = None
        self._last_driven: float | None = None
        self._renewed_at: float | None = None
        self._heard = False

    def heard(self) -> None:
        self._heard = True

    def _start_over(self, why: str, *args: object) -> None:
        self._driven = 0.0
        if self._renewed_at is not None:
            self._renewed_at = None
            self._logger.info(why, *args)

    def tick(self, *, driving: bool) -> None:
        now = self._monotonic()
        if self._heard:
            self._heard = False
            self._start_over("The OSR2 is heard again")
        if driving:
            if self._last_tick is not None:
                self._driven += now - self._last_tick
            self._last_driven = now
        elif self._last_driven is not None and now - self._last_driven > self.FORGOTTEN_AFTER_S:
            self._start_over("The OSR2 has not been driven for %.0f minutes: "
                             "no longer counted as not answering", self.FORGOTTEN_AFTER_S / 60)
        self._last_tick = now
        if self._driven < self.DRIVEN_S:
            return
        if self._renewed_at is None:
            self._logger.info("The OSR2 has said nothing through %.0f minutes of driving: "
                              "counted as not answering", self.DRIVEN_S / 60)
        if self._renewed_at is None or now - self._renewed_at >= self.RENEWED_EVERY_S:
            publish_stamp(self._stamp_file)
            self._renewed_at = now
