from __future__ import annotations

import threading
import time
from collections.abc import Callable

QUIET_S = 2.0

MFP = "MFP"
UDP = "T-Code UDP"
HOLD = "a hold"


def tcode_from(sender: str) -> str:
    return f"T-Code from {sender}"


class RunLog:
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
