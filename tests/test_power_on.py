"""Noticing the OSR2 come back on, from its own chatter.

Its port stays enumerated with the power off, so the only thing that says the
device is on is that it is talking -- which is already how the idle monitor
decides. These pin where one spell of talking ends and the next begins.
"""
from __future__ import annotations

from pathlib import Path

from osr2_broker.power_on import PowerOnWatch


def _build(tmp_path: Path, clock: list[float], *, stamped: float | None = None,
           wall: float = 1_000_000.0) -> PowerOnWatch:
    rx_file = tmp_path / "osr2_serial_rx.txt"
    if stamped is not None:
        rx_file.write_text(str(stamped), encoding="utf-8")
    return PowerOnWatch(
        rx_stamp_file=rx_file, monotonic=lambda: clock[0], wall_clock=lambda: wall,
    )


def test_the_first_line_of_a_run_is_a_power_on_when_nothing_was_stamped_before_it(tmp_path):
    watch = _build(tmp_path, [10.0])
    assert watch.rx_broke_the_silence() is True


def test_a_broker_restarting_while_the_device_talks_does_not_call_that_a_power_on(tmp_path):
    """The stamp outlives the process, so a supervisor restart mid-session is
    not mistaken for the switch being flipped."""
    watch = _build(tmp_path, [10.0], stamped=999_990.0, wall=1_000_000.0)
    assert watch.rx_broke_the_silence() is False


def test_the_line_after_a_power_on_is_not_another_one(tmp_path):
    """A power-on is the edge, not the state: the chatter that follows it is
    the same spell of talking, and re-parking on every line would fight
    whatever is driving the device."""
    clock = [10.0]
    watch = _build(tmp_path, clock)
    assert watch.rx_broke_the_silence() is True

    clock[0] = 10.5
    assert watch.rx_broke_the_silence() is False


def test_the_device_going_quiet_and_speaking_again_is_a_power_on(tmp_path):
    """The broker outlives the switch: it is one long-running process that sees
    the device go off and come back, and that gap is the whole signal."""
    clock = [10.0]
    watch = _build(tmp_path, clock, stamped=999_999.0, wall=1_000_000.0)
    assert watch.rx_broke_the_silence() is False

    clock[0] = 10.0 + PowerOnWatch.SILENCE_SECONDS
    assert watch.rx_broke_the_silence() is True
