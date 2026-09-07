"""Noticing that the OSR2 has just been switched on.

Its USB adapter stays enumerated with the power off, so COM4's presence says
nothing about the device.  What does say something is its own chatter: a
powered OSR2 sends serial lines of its own accord and a switched-off one sends
none, which is already how the idle monitor decides the device is on.  The
first line after a long enough silence is therefore the device coming back.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import stamp_age


class PowerOnWatch:
    """Where one spell of the OSR2 talking ends and the next one begins."""

    # Double the 30s within which the idle monitor calls the device on from
    # its RX stamp, and which it has held for fifteen minutes at a stretch --
    # so 30s is the observed ceiling on the gaps a powered OSR2 leaves.
    # Erring long is deliberate: a missed park costs one button press, a
    # false one moves the device while it is in use.
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
        """Record that the OSR2 just spoke; whether it had been silent first."""
        now = self._monotonic()
        previous, self._last_rx = self._last_rx, now
        if previous is None:
            return self._silent_before_this_run
        return now - previous >= self.SILENCE_SECONDS
