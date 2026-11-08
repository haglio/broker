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
    watch = _build(tmp_path, [10.0], stamped=999_990.0, wall=1_000_000.0)
    assert watch.rx_broke_the_silence() is False


def test_the_line_after_a_power_on_is_not_another_one_parking_on_each_would_fight_whatever_drives_the_device(tmp_path):
    clock = [10.0]
    watch = _build(tmp_path, clock)
    assert watch.rx_broke_the_silence() is True

    clock[0] = 10.5
    assert watch.rx_broke_the_silence() is False


def test_the_device_going_quiet_and_speaking_again_is_a_power_on_its_adapter_stays_listed_with_the_power_off(tmp_path):
    clock = [10.0]
    watch = _build(tmp_path, clock, stamped=999_999.0, wall=1_000_000.0)
    assert watch.rx_broke_the_silence() is False

    clock[0] = 10.0 + PowerOnWatch.SILENCE_SECONDS
    assert watch.rx_broke_the_silence() is True


def test_a_silence_short_of_four_reports_is_not_a_power_on_erring_long_costs_a_press_erring_short_moves_a_device_in_use(tmp_path):
    clock = [10.0]
    watch = _build(tmp_path, clock)
    watch.rx_broke_the_silence()

    clock[0] += 59.9

    assert watch.rx_broke_the_silence() is False


def test_a_silence_of_four_report_gaps_a_minute_is_a_power_on(tmp_path):
    clock = [10.0]
    watch = _build(tmp_path, clock)
    watch.rx_broke_the_silence()

    clock[0] += 60.0

    assert watch.rx_broke_the_silence() is True
