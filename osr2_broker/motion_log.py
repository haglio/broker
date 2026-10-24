"""Who is driving the OSR2, and when they started.

Four writers reach the device -- MFP through the virtual port, T-Code over
loopback UDP, the sender holding the OSR2's slot, and the broker's own park or
retract -- and the log said nothing about any of them, so "the OSR2 started
moving too early" could only be answered by guessing which one it was. Every
write passes through here, and a run of them is reported at its two ends rather
than per waypoint; so is a run of the T-Code UDP dropped while a sender holds
the slot.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

# How long without another counts as a run being over.  Longer than the gap
# between a script's waypoints (~100ms) and than a hold's settle, so a stretch
# of ordinary driving reads as one run rather than a line per write.
QUIET_S = 2.0

MFP = "MFP"
UDP = "T-Code UDP"
HOLD = "a hold"


def tcode_from(sender: str) -> str:
    return f"T-Code from {sender}"


class RunLog:
    """Something that comes in runs, said at each run's two ends rather than
    each time it happens: a run is one key again and again, and ends at a quiet
    spell or at another key.

    Called from several threads at once, so every field is under one lock --
    and the lines go out outside it, the logger having one of its own.
    """

    def __init__(self, *, logger, began: Callable[[str, float | None], str],
                 ended: Callable[[str, float, int], str],
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._logger = logger
        self._began = began
        self._ended = ended
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._key: str | None = None
        self._started = 0.0
        self._last: float | None = None
        self._times = 0

    def happened(self, key: str) -> None:
        now = self._monotonic()
        with self._lock:
            running, last = self._key, self._last
            if running == key and now - last < QUIET_S:
                self._last = now
                self._times += 1
                return
            ran_for = None if running is None else last - self._started
            quiet_for = None if last is None or running is not None else now - last
            times = self._times
            self._key, self._started, self._last, self._times = key, now, now, 1
        if ran_for is not None:
            self._logger.info(self._ended(running, ran_for, times))
        self._logger.info(self._began(key, quiet_for))

    def running(self) -> str | None:
        now = self._monotonic()
        with self._lock:
            if self._key is None or now - self._last >= QUIET_S:
                return None
            return self._key

    def tick(self) -> None:
        """Called on the broker's own beat; closes a run out once it is over."""
        now = self._monotonic()
        with self._lock:
            if self._key is None or now - self._last < QUIET_S:
                return
            running, ran_for, times = self._key, self._last - self._started, self._times
            self._key = None
        self._logger.info(self._ended(running, ran_for, times))


def _driven_by(source: str, quiet_for: float | None) -> str:
    if quiet_for is None:
        return f"OSR2 driven by {source}"
    return f"OSR2 driven by {source}, quiet for {quiet_for:.1f}s before that"


def _quiet_after(source: str, ran_for: float, _writes: int) -> str:
    return f"OSR2 quiet after {ran_for:.1f}s of {source}"


def motion_log(*, logger, monotonic: Callable[[], float] = time.monotonic) -> RunLog:
    return RunLog(logger=logger, began=_driven_by, ended=_quiet_after, monotonic=monotonic)


def driven_from_outside(motion: RunLog) -> bool:
    return motion.running() not in (None, HOLD)


def _dropping(holder: str, _quiet_for: float | None) -> str:
    return f"Dropping {UDP} while the OSR2 is {holder}'s"


def _dropped(holder: str, _ran_for: float, lines: int) -> str:
    return f"Dropped {lines} {UDP} line{'' if lines == 1 else 's'} while the OSR2 was {holder}'s"


def dropped_udp_log(*, logger, monotonic: Callable[[], float] = time.monotonic) -> RunLog:
    return RunLog(logger=logger, began=_dropping, ended=_dropped, monotonic=monotonic)
