from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import publish_stamp

_ANSWER = re.compile(r"\btcode\s+v\d", re.IGNORECASE)


class DeviceQuestion:
    QUESTION = b"D1\n"
    EVERY_SECONDS = 0.25
    A_DEVICE_STILL_STARTING_UP_ANSWERS_WITHIN_SECONDS = 10.0
    UNANSWERED_BEFORE_WARNING = int(A_DEVICE_STILL_STARTING_UP_ANSWERS_WITHIN_SECONDS / EVERY_SECONDS)

    def __init__(self, *, answer_file: Path, monotonic: Callable[[], float], logger,
                 wall_clock: Callable[[], float] = time.time):
        self._answer_file = answer_file
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._logger = logger
        self._asked_at: float | None = None
        self._answered = False
        self._unanswered = 0
        self._warned = False
        self._standing_down = False

    def due(self) -> bool:
        return (self._asked_at is None
                or self._monotonic() - self._asked_at >= self.EVERY_SECONDS)

    def asked(self) -> None:
        self._asked_at = self._monotonic()
        self._unanswered += 1
        self._standing_down = False

    def stand_down(self) -> None:
        if self._standing_down:
            return
        self._standing_down = True
        publish_stamp(self._answer_file, 0.0)

    def heard(self, line: str) -> None:
        if _ANSWER.search(line):
            publish_stamp(self._answer_file, self._wall_clock())
            self._unanswered = 0
            if not self._answered:
                self._answered = True
                self._logger.info("The OSR2 answers the broker's question: %r", line)
            return
        if self._unanswered >= self.UNANSWERED_BEFORE_WARNING and not self._warned:
            self._warned = True
            self._logger.warning(
                "The OSR2 has answered none of the broker's last %d questions; it says %r",
                self._unanswered, line)
