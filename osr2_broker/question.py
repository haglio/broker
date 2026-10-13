"""Asking the OSR2 a question only a switched-on device can answer.

Its USB adapter stays enumerated with the power off and takes whatever is
written to it, and on its own a powered OSR2 says something only about every
15 s.  Asked for its T-Code version it answers at once, so the answers, stamped
where every app reads them (app_support's osr2_device), say within a second
that it has been switched off.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import publish_stamp

# What the device says to "D1": the T-Code version it speaks, as "TCode v0.3".
_ANSWER = re.compile(r"\btcode\s+v\d", re.IGNORECASE)


class DeviceQuestion:
    QUESTION = b"D1\n"
    EVERY_SECONDS = 0.25
    # Ten seconds of questions: long enough that a device still starting up is
    # not reported, short enough that the log says early what it answers instead.
    UNANSWERED_BEFORE_WARNING = 40

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
        """Stop the answers counting: from long ago, the last one keeps no app
        listening for the next."""
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
