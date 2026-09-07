"""Who is driving the OSR2, and when they started.

Three writers reach the device -- MFP through the virtual port, T-Code over
loopback UDP, and the broker's own park or retract -- and the log said nothing
about any of them, so "the OSR2 started moving too early" could only be answered
by guessing which one it was. Every write passes through here, and a run of them
is reported at its two ends rather than per waypoint.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

# How long without a write counts as the device being still.  Longer than the
# gap between a script's waypoints (~100ms) and than a hold's settle, so a
# stretch of ordinary driving reads as one run rather than a line per write.
QUIET_S = 2.0

MFP = "MFP"
UDP = "T-Code UDP"
HOLD = "a hold"


class MotionLog:
    """The device's motion, said at its edges.

    Called from both forwarding threads, the UDP listener and the tick, so every
    field is under one lock -- and the lines go out outside it, the logger having
    one of its own.
    """

    def __init__(self, *, logger, quiet_s: float = QUIET_S,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._logger = logger
        self._quiet_s = quiet_s
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._source: str | None = None
        self._started = 0.0
        self._last: float | None = None

    def wrote(self, source: str) -> None:
        """One write reached the device, from *source*."""
        now = self._monotonic()
        with self._lock:
            running, last = self._source, self._last
            if running == source and last is not None and now - last < self._quiet_s:
                self._last = now
                return
            ran_for = None if running is None else last - self._started
            quiet_for = None if last is None or running is not None else now - last
            self._source, self._started, self._last = source, now, now
        if ran_for is not None:
            self._logger.info("OSR2 quiet after %.1fs of %s", ran_for, running)
        if quiet_for is None:
            self._logger.info("OSR2 driven by %s", source)
        else:
            self._logger.info("OSR2 driven by %s, quiet for %.1fs before that",
                              source, quiet_for)

    def tick(self) -> None:
        """Called on the broker's own beat; closes a run out once it is over."""
        now = self._monotonic()
        with self._lock:
            if self._source is None or self._last is None:
                return
            if now - self._last < self._quiet_s:
                return
            running, ran_for = self._source, self._last - self._started
            self._source = None
        self._logger.info("OSR2 quiet after %.1fs of %s", ran_for, running)
