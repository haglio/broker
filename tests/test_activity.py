from __future__ import annotations

from pathlib import Path

from osr2_broker.activity import ActivityStamp


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


def test_a_second_mark_inside_the_interval_leaves_the_file_alone(tmp_path: Path):
    path = tmp_path / "osr2_serial_rx.txt"
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS - 0.1
    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900000.0"


def test_a_failed_write_still_spends_the_interval(tmp_path: Path):
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
