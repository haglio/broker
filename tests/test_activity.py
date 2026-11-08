from __future__ import annotations

from pathlib import Path

from app_support.osr2_device import SILENT_ONCE_OFF_S

from osr2_broker.activity import ActivityStamp
from osr2_broker.monitor import IN_USE_THRESHOLD
from osr2_broker.power_on import PowerOnWatch


def test_stamp_writes_the_wall_clock_to_its_file(tmp_path: Path):
    path = tmp_path / "osr2_serial_rx.txt"
    stamp = ActivityStamp(path, wall_clock=lambda: 1711900000.0)

    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900000.0"


def test_a_mark_past_the_interval_refreshes_the_file(tmp_path: Path):
    path = tmp_path / "osr2_serial_rx.txt"
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS
    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900005.0"


def test_a_mark_comes_with_every_byte_so_a_second_inside_the_interval_writes_nothing(tmp_path: Path):
    path = tmp_path / "osr2_serial_rx.txt"
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS - 0.1
    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900000.0"


def test_a_failed_write_still_spends_the_interval_rather_than_retrying_on_every_byte(tmp_path: Path):
    path = tmp_path / "blocked" / "osr2_serial_rx.txt"
    path.parent.write_text("", encoding="utf-8")
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()
    path.parent.unlink()
    path.parent.mkdir()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS - 0.1
    stamp.mark()

    assert not path.exists()


def test_a_file_that_cannot_be_written_does_not_reach_the_forwarding_loop(tmp_path: Path):
    path = tmp_path / "blocked" / "osr2_serial_rx.txt"
    path.parent.write_text("", encoding="utf-8")
    stamp = ActivityStamp(path, wall_clock=lambda: 1711900000.0)

    stamp.mark()

    assert not path.exists()


def test_the_interval_is_far_under_the_shortest_silence_its_readers_judge_the_device_by():
    assert ActivityStamp.WRITE_INTERVAL_SECONDS * 4 <= SILENT_ONCE_OFF_S
    assert ActivityStamp.WRITE_INTERVAL_SECONDS * 4 <= IN_USE_THRESHOLD
    assert ActivityStamp.WRITE_INTERVAL_SECONDS * 4 <= PowerOnWatch.SILENCE_SECONDS
