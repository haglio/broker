from __future__ import annotations

import threading
from dataclasses import dataclass

from app_support import osr2_hold


@dataclass(frozen=True)
class Hold:
    tcode: bytes
    fired_message: str


def _hold(verb: str, fired_message: str) -> Hold:
    return Hold(f"{osr2_hold.hold_tcode(verb)}\n".encode("ascii"), fired_message)


PARK = _hold(osr2_hold.PARK, "Parking OSR2 at position 0")
RETRACT = _hold(osr2_hold.RETRACT, "Retracting OSR2 to position 9999")


class HoldScheduler:
    HEAL_WITHOUT_RESUME_SECONDS = 5.0
    UNMUTED_SETTLE_SECONDS = 1.0

    def __init__(self, *, monotonic, logger):
        self._monotonic = monotonic
        self._logger = logger
        self._lock = threading.Lock()
        self._pending: Hold = PARK
        self._pending_time: float | None = None
        self._suppressed_since: float | None = None

    def schedule(self, hold: Hold, message: str) -> None:
        with self._lock:
            armed = self._arm_with_the_lock_already_held(hold, wait_seconds=0.0)
            self._suppressed_since = self._monotonic()
        if armed:
            self._logger.info(message)

    def schedule_without_muting(self, hold: Hold, message: str) -> None:
        with self._lock:
            if not self._arm_with_the_lock_already_held(
                    hold, wait_seconds=self.UNMUTED_SETTLE_SECONDS):
                return
        self._logger.info(message)

    def _arm_with_the_lock_already_held(self, hold: Hold, *, wait_seconds: float) -> bool:
        due = self._monotonic() + wait_seconds
        if self._pending_time is not None and hold == self._pending:
            self._pending_time = min(self._pending_time, due)
            return False
        self._pending = hold
        self._pending_time = due
        return True

    def cancel(self) -> None:
        with self._lock:
            self._pending_time = None
            self._suppressed_since = None

    def suppresses_mfp(self) -> bool:
        with self._lock:
            since = self._suppressed_since
            if since is None:
                return False
            if self._monotonic() - since < self.HEAL_WITHOUT_RESUME_SECONDS:
                return True
            self._suppressed_since = None
        self._logger.info("MFP active after hold grace; resuming forwarding")
        return False

    def fire_due(self, real_port, serial_write_lock, on_written) -> Hold | None:
        with self._lock:
            if self._pending_time is None:
                return None
            if self._monotonic() < self._pending_time:
                return None
            hold = self._pending
            self._pending_time = None
        with serial_write_lock:
            real_port.write(hold.tcode)
        on_written()
        self._logger.info(hold.fired_message)
        return hold
