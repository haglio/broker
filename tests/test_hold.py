from __future__ import annotations

import threading
from unittest.mock import MagicMock

from osr2_broker.hold import PARK, RETRACT, HoldScheduler


def _nothing() -> None:
    pass


def _build(clock: list[float]):
    logger = MagicMock()
    return HoldScheduler(monotonic=lambda: clock[0], logger=logger), logger


def test_a_scheduled_hold_is_not_written_until_the_settle_delay_has_passed():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    holds.fire_due(real_port, lock, _nothing)

    real_port.write.assert_not_called()

    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, lock, _nothing)

    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_a_park_sets_the_device_down_at_home_over_a_whole_second():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 11.0
    holds.fire_due(real_port, threading.Lock(), _nothing)

    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_scheduling_mutes_mfp_at_once_rather_than_when_the_write_lands():
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
    clock = [10.0]
    holds, logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.0 + HoldScheduler.SUPPRESS_GRACE_SECONDS

    assert holds.suppresses_mfp() is False
    assert holds.suppresses_mfp() is False

    healed = [c for c in logger.info.call_args_list
              if c.args[0] == "MFP active after hold grace; resuming forwarding"]
    assert len(healed) == 1, healed


def test_cancelling_drops_both_the_pending_write_and_the_mute():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    holds.cancel()
    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS

    assert holds.fire_due(real_port, threading.Lock(), _nothing) is None
    real_port.write.assert_not_called()
    assert holds.suppresses_mfp() is False


def test_a_handover_park_is_scheduled_without_muting_mfp():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()

    holds.schedule_without_muting(PARK, "Auto mode deactivated: park scheduled")

    assert holds.suppresses_mfp() is False

    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, threading.Lock(), _nothing)

    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_a_fired_hold_is_handed_back_to_the_caller():
    clock = [10.0]
    holds, _logger = _build(clock)
    lock = threading.Lock()

    holds.schedule(RETRACT, "OmniPause: retract scheduled")

    assert holds.fire_due(MagicMock(), lock, _nothing) is None

    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS

    assert holds.fire_due(MagicMock(), lock, _nothing) is RETRACT


def test_a_second_hold_replaces_the_one_still_waiting_out_its_delay():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.5
    holds.schedule(RETRACT, "OmniPause: retract scheduled")

    clock[0] = 11.0
    holds.fire_due(real_port, lock, _nothing)
    real_port.write.assert_not_called()

    clock[0] = 11.5
    holds.fire_due(real_port, lock, _nothing)
    real_port.write.assert_called_once_with(b"L09999I500\n")


def test_the_same_hold_asked_for_again_keeps_the_deadline_it_has():
    clock = [10.0]
    holds, logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.5
    holds.schedule(PARK, "OmniPause: park scheduled")

    clock[0] = 11.0
    holds.fire_due(real_port, lock, _nothing)

    real_port.write.assert_called_once_with(b"L00000I1000\n")
    scheduled = [c.args[0] for c in logger.info.call_args_list]
    assert scheduled.count("OmniPause: park scheduled") == 1


def test_the_hold_is_written_under_the_caller_s_serial_lock():
    clock = [10.0]
    holds, _logger = _build(clock)
    lock = threading.Lock()
    held_during_write = []

    class FakeReal:
        def write(self, _data):
            held_during_write.append(lock.locked())

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 11.0
    holds.fire_due(FakeReal(), lock, _nothing)

    assert held_during_write == [True]


def test_the_direct_write_is_recorded_before_the_hold_is_logged():
    clock = [10.0]
    holds, logger = _build(clock)
    order: list[str] = []
    logger.info.side_effect = lambda *_a: order.append("logged")

    holds.schedule(PARK, "OmniPause: park scheduled")
    order.clear()
    clock[0] = 11.0
    holds.fire_due(MagicMock(), threading.Lock(), lambda: order.append("recorded"))

    assert order == ["recorded", "logged"]


def test_the_settle_delay_is_one_second():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")

    clock[0] = 10.9
    assert holds.fire_due(real_port, lock, _nothing) is None

    clock[0] = 11.0
    assert holds.fire_due(real_port, lock, _nothing) is PARK


def test_the_mute_grace_is_five_seconds():
    clock = [10.0]
    holds, _logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")

    clock[0] = 14.9
    assert holds.suppresses_mfp() is True

    clock[0] = 15.0
    assert holds.suppresses_mfp() is False


def test_a_park_arriving_mid_check_keeps_the_mute_it_just_asked_for():
    clock = [100.0]
    at_the_comparison = threading.Event()
    _slipped_in = threading.Event()

    def monotonic() -> float:
        if threading.current_thread().name == "broker-virtual":
            at_the_comparison.set()
            _slipped_in.wait(timeout=0.25)
        return clock[0]

    holds = HoldScheduler(monotonic=monotonic, logger=MagicMock())
    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 100.0 + HoldScheduler.SUPPRESS_GRACE_SECONDS

    def tick():
        at_the_comparison.wait(timeout=5.0)
        holds.schedule(PARK, "OmniPause: park scheduled")
        _slipped_in.set()

    reader = threading.Thread(target=holds.suppresses_mfp, name="broker-virtual")
    ticker = threading.Thread(target=tick, name="broker-session")
    ticker.start()
    reader.start()
    reader.join(timeout=5.0)
    ticker.join(timeout=5.0)

    assert not reader.is_alive()
    assert not ticker.is_alive()
    assert holds.suppresses_mfp() is True


def test_a_hold_fires_once_and_is_not_replayed_on_the_next_tick():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.0 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, lock, _nothing)
    holds.fire_due(real_port, lock, _nothing)

    real_port.write.assert_called_once_with(b"L00000I1000\n")
