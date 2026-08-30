"""The hold scheduler: where the device is sent, when, and what is muted for it.

A hold is one T-Code move to a fixed position, written a settle delay after it
is asked for, with the MFP script feed muted across the gap so an in-flight tail
cannot undo it. These are the mechanics; tests/test_session.py covers which verb
reaches which of them.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

from osr2_broker.hold import PARK, RETRACT, HoldScheduler


def _build(clock: list[float]):
    logger = MagicMock()
    return HoldScheduler(monotonic=lambda: clock[0], logger=logger), logger


def test_a_scheduled_hold_is_not_written_until_the_settle_delay_has_passed():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    holds.fire_due(real_port, lock)

    real_port.write.assert_not_called()

    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, lock)

    real_port.write.assert_called_once_with(b"L00000I500\n")


def test_scheduling_mutes_mfp_at_once_rather_than_when_the_write_lands():
    """The mute has to start before the delay, not after it: what it is there to
    swallow is the script tail already on its way while the device settles."""
    clock = [10.0]
    holds, _logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")

    assert holds.suppresses_mfp() is True


def test_a_hold_that_is_only_pending_leaves_mfp_alone_until_it_is_scheduled():
    clock = [10.0]
    holds, _logger = _build(clock)

    assert holds.suppresses_mfp() is False


def test_the_mute_survives_to_the_last_moment_of_the_grace_window():
    clock = [10.0]
    holds, _logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.0 + HoldScheduler.SUPPRESS_GRACE_SECONDS - 0.001

    assert holds.suppresses_mfp() is True


def test_the_mute_heals_itself_once_the_grace_window_has_elapsed():
    """A RESUME that never arrives must not mute the device forever. Asking at
    all means MFP has live data, so past the window the latch lets go."""
    clock = [10.0]
    holds, logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.0 + HoldScheduler.SUPPRESS_GRACE_SECONDS

    assert holds.suppresses_mfp() is False
    assert holds.suppresses_mfp() is False  # and it stays let go
    logger.info.assert_any_call("MFP active after hold grace; resuming forwarding")


def test_cancelling_drops_both_the_pending_write_and_the_mute():
    """RESUME undoes the whole hold, not half of it: a cancel that left the mute
    latched would leave MFP silent with nothing coming to clear it."""
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    holds.cancel()
    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS

    assert holds.fire_due(real_port, threading.Lock()) is None
    real_port.write.assert_not_called()
    assert holds.suppresses_mfp() is False


def test_a_handover_park_is_scheduled_without_muting_mfp():
    """Auto mode letting go is not OmniPause: MFP is what takes the device back,
    so muting it would be muting the thing that is meant to take over."""
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()

    holds.schedule_without_muting(PARK, "Auto mode deactivated: park scheduled")

    assert holds.suppresses_mfp() is False

    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, threading.Lock())

    real_port.write.assert_called_once_with(b"L00000I500\n")


def test_a_fired_hold_is_handed_back_to_the_caller():
    """The caller stamps its T-Code suppression window off this, so firing has to
    be distinguishable from a tick where nothing was due."""
    clock = [10.0]
    holds, _logger = _build(clock)
    lock = threading.Lock()

    holds.schedule(RETRACT, "OmniPause: retract scheduled")

    assert holds.fire_due(MagicMock(), lock) is None

    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS

    assert holds.fire_due(MagicMock(), lock) is RETRACT


def test_a_hold_fires_once_and_is_not_replayed_on_the_next_tick():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, lock)
    holds.fire_due(real_port, lock)

    real_port.write.assert_called_once_with(b"L00000I500\n")
