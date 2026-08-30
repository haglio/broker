"""Sending the OSR2 to a fixed position, and muting MFP while it goes there.

A hold is one T-Code move written a settle delay after it is asked for. The
delay exists so the mute can start first: MFP's script feed is swallowed across
the gap, and the in-flight tail cannot immediately undo the move.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Hold:
    """A fixed position the broker sends the device to and keeps it at.

    PARK is home, where a session's motion ends.  RETRACT is its antonym — the
    far end of the stroke, for when the device has to be away from the user now.
    The two differ only in where they land and in what the log calls it: both are
    one T-Code move, both wait out the same settle delay, and both mute the
    script feed around it so an in-flight tail cannot undo them.
    """

    tcode: bytes
    fired_message: str


PARK = Hold(b"L00000I500\n", "OmniPause: parking OSR2 at position 0")
RETRACT = Hold(b"L09999I500\n", "OmniPause: retracting OSR2 to position 9999")


class HoldScheduler:
    """The pending hold and the mute latch, guarded.

    Two threads reach in. The main tick schedules, cancels and fires; the
    broker-virtual forwarding thread asks whether MFP is muted -- and that
    question is a read, a comparison against the clock and a clear, which is
    long enough for a PARK to land in the middle of it and be thrown away
    (tests/test_hold.py reconstructs it). So every touch of the three fields is
    under one lock, matching what the sibling BrokerAutoController already does
    with its own flags.

    Nothing that can block is done while holding it: the log lines and the
    serial write are outside, the latter also because it takes a second lock.
    """

    DELAY_SECONDS = 1.0
    # After a hold is scheduled, MFP forwarding is muted for this long to swallow
    # the in-flight script tail. Past it, live MFP data self-heals the mute so a
    # lost RESUME can't leave the device muted indefinitely.
    SUPPRESS_GRACE_SECONDS = 5.0

    def __init__(self, *, monotonic, logger):
        self._monotonic = monotonic
        self._logger = logger
        self._lock = threading.Lock()
        self._pending: Hold = PARK
        self._pending_time: float | None = None
        self._suppressed_since: float | None = None

    def schedule(self, hold: Hold, message: str) -> None:
        """Send the device to *hold*'s position once the settle delay elapses.

        The mute starts now and the write lands a delay later, so the script
        feed's tail is swallowed before the device is told where to go.
        """
        with self._lock:
            self._arm(hold)
            self._suppressed_since = self._monotonic()
        self._logger.info(message)

    def schedule_without_muting(self, hold: Hold, message: str) -> None:
        """Schedule *hold* and leave the MFP feed running to reach it.

        Auto mode letting go is not OmniPause: MFP is what takes the device
        back, so there is nothing here to swallow.
        """
        with self._lock:
            self._arm(hold)
        self._logger.info(message)

    def _arm(self, hold: Hold) -> None:
        """Called with the lock held."""
        self._pending = hold
        self._pending_time = self._monotonic() + self.DELAY_SECONDS

    def cancel(self) -> None:
        """Drop the pending write and let the mute go — what RESUME means."""
        with self._lock:
            self._pending_time = None
            self._suppressed_since = None

    def suppresses_mfp(self) -> bool:
        """Whether a scheduled hold is currently muting MFP->OSR2 forwarding.

        The mute is a grace window that swallows the in-flight script tail so it
        can't immediately undo the hold. It normally ends on RESUME, but a
        lost RESUME must not mute forever: once the window elapses, the presence
        of live MFP data (the caller only asks while forwarding a packet) means
        the user wants motion, so the latch self-heals rather than waiting on a
        RESUME that may never arrive.
        """
        with self._lock:
            since = self._suppressed_since
            if since is None:
                return False
            if self._monotonic() - since < self.SUPPRESS_GRACE_SECONDS:
                return True
            self._suppressed_since = None
        self._logger.info("MFP active after hold grace; resuming forwarding")
        return False

    def fire_due(self, real_port, serial_write_lock) -> Hold | None:
        with self._lock:
            if self._pending_time is None:
                return None
            if self._monotonic() < self._pending_time:
                return None
            hold = self._pending
            self._pending_time = None
        with serial_write_lock:
            real_port.write(hold.tcode)
        self._logger.info(hold.fired_message)
        return hold
