from __future__ import annotations

import threading
from unittest.mock import MagicMock

from osr2_broker.hold import PARK, RETRACT, HoldScheduler

_WAITED_OUT_IN_FULL_WHEN_THE_LOCK_HOLDS = 0.25


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


def test_mfp_is_muted_the_moment_a_hold_is_asked_for_so_its_script_tail_cannot_undo_the_move():
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
    clock[0] = 10.0 + HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS - 0.001

    assert holds.suppresses_mfp() is True


def test_the_healed_mute_says_so_once_though_mfp_asks_on_every_packet():
    clock = [10.0]
    holds, logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.0 + HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS

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


def test_a_handover_park_leaves_mfp_unmuted_mfp_is_what_takes_the_device_back():
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


def test_a_retract_during_a_park_s_delay_is_the_emergency_and_replaces_it_rather_than_being_dropped():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.5
    holds.schedule(RETRACT, "OmniPause: retract scheduled")

    when_the_park_would_have_fired = 10.0 + HoldScheduler.DELAY_SECONDS
    clock[0] = when_the_park_would_have_fired
    holds.fire_due(real_port, lock, _nothing)
    real_port.write.assert_not_called()

    clock[0] = 10.5 + HoldScheduler.DELAY_SECONDS
    holds.fire_due(real_port, lock, _nothing)
    real_port.write.assert_called_once_with(b"L09999I500\n")


def test_a_hold_asked_for_every_tick_keeps_its_first_deadline_so_the_write_is_never_pushed_out():
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


def test_the_direct_write_is_recorded_before_the_slow_log_line_mfp_s_thread_runs_the_moment_the_lock_drops():
    clock = [10.0]
    holds, logger = _build(clock)
    order: list[str] = []
    logger.info.side_effect = lambda *_a: order.append("logged")

    holds.schedule(PARK, "OmniPause: park scheduled")
    order.clear()
    clock[0] = 11.0
    holds.fire_due(MagicMock(), threading.Lock(), lambda: order.append("recorded"))

    assert order == ["recorded", "logged"]


def test_the_settle_delay_is_a_literal_second_shorter_would_write_the_hold_into_the_script_tail():
    clock = [10.0]
    holds, _logger = _build(clock)
    real_port = MagicMock()
    lock = threading.Lock()

    holds.schedule(PARK, "OmniPause: park scheduled")

    clock[0] = 10.9
    assert holds.fire_due(real_port, lock, _nothing) is None

    clock[0] = 11.0
    assert holds.fire_due(real_port, lock, _nothing) is PARK


def test_the_mute_heals_without_a_resume_after_five_literal_seconds_a_lost_resume_costs_no_more():
    clock = [10.0]
    holds, _logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")

    clock[0] = 14.9
    assert holds.suppresses_mfp() is True

    clock[0] = 15.0
    assert holds.suppresses_mfp() is False


def test_the_mute_outlasts_the_settle_delay_or_mfp_would_undo_the_hold_it_just_wrote():
    assert HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS > HoldScheduler.DELAY_SECONDS


def test_a_hold_asked_for_again_renews_the_mute_though_its_deadline_and_log_line_are_absorbed():
    clock = [10.0]
    holds, _logger = _build(clock)

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.5
    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 10.5 + HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS - 0.1

    assert holds.suppresses_mfp() is True


def test_nothing_that_can_block_runs_under_the_scheduler_s_lock_not_the_log_lines_nor_the_write_which_takes_the_serial_lock_too():
    clock = [10.0]
    holds, logger = _build(clock)
    lock_held: list[bool] = []
    logger.info.side_effect = lambda *_a: lock_held.append(holds._lock.locked())

    class FakeReal:
        def write(self, _data):
            lock_held.append(holds._lock.locked())

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 11.0
    holds.fire_due(FakeReal(), threading.Lock(), _nothing)
    clock[0] = 11.0 + HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS
    holds.suppresses_mfp()
    holds.schedule_without_muting(RETRACT, "OSR2 powered on: park scheduled")

    assert lock_held == [False] * 5


def test_a_park_arriving_mid_check_keeps_the_mute_it_just_asked_for():
    clock = [100.0]
    at_the_comparison = threading.Event()
    _slipped_in = threading.Event()

    def monotonic() -> float:
        if threading.current_thread().name == "broker-virtual":
            at_the_comparison.set()
            _slipped_in.wait(timeout=_WAITED_OUT_IN_FULL_WHEN_THE_LOCK_HOLDS)
        return clock[0]

    holds = HoldScheduler(monotonic=monotonic, logger=MagicMock())
    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 100.0 + HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS

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


def test_the_direct_write_is_recorded_only_once_it_is_written():
    clock = [10.0]
    holds, _logger = _build(clock)
    order: list[str] = []

    class FakeReal:
        def write(self, _data):
            order.append("written")

    holds.schedule(PARK, "OmniPause: park scheduled")
    clock[0] = 11.0
    holds.fire_due(FakeReal(), threading.Lock(), lambda: order.append("recorded"))

    assert order == ["written", "recorded"]
