"""The activity stamp: one file, one clock, one throttle.

The monitor reads these files to decide whether the OSR2 is on and whether it is
in use, so what matters here is the wall-clock value that lands on disk and how
often it is allowed to land.
"""
from __future__ import annotations

from pathlib import Path

from osr2_broker.activity import ActivityStamp


def test_stamp_writes_the_wall_clock_to_its_file(tmp_path: Path):
    path = tmp_path / "osr2_serial_rx.txt"
    stamp = ActivityStamp(path, wall_clock=lambda: 1711900000.0)

    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900000.0"


def test_a_mark_past_the_interval_refreshes_the_file(tmp_path: Path):
    """The other side of the same comparison. Pinned on its own, so the throttle
    cannot degrade into 'never write again' with the suite still green."""
    path = tmp_path / "osr2_serial_rx.txt"
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS
    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900005.0"


def test_a_second_mark_inside_the_interval_leaves_the_file_alone(tmp_path: Path):
    """Every byte off the serial port would otherwise be a disk write. The
    monitor's thresholds are tens of seconds wide, so a stamp that is seconds old
    is as good as a fresh one."""
    path = tmp_path / "osr2_serial_rx.txt"
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS - 0.1
    stamp.mark()

    assert path.read_text(encoding="utf-8") == "1711900000.0"


def test_a_failed_write_still_spends_the_interval(tmp_path: Path):
    """The throttle is advanced before the write is attempted, so a directory
    that has gone away costs one stamp rather than turning the throttle off and
    putting a write attempt on every byte off the serial port until it comes
    back."""
    path = tmp_path / "blocked" / "osr2_serial_rx.txt"
    path.parent.write_text("", encoding="utf-8")  # a file where the directory should be
    now = [1711900000.0]
    stamp = ActivityStamp(path, wall_clock=lambda: now[0])

    stamp.mark()  # nothing can be made under a file, so this one cannot land
    path.parent.unlink()
    path.parent.mkdir()
    now[0] += ActivityStamp.WRITE_INTERVAL_SECONDS - 0.1
    stamp.mark()

    assert not path.exists()


def test_a_file_that_cannot_be_written_does_not_reach_the_forwarding_loop(tmp_path: Path):
    """The stamp is a courtesy to the monitor, and it is marked from inside the
    two loops that carry the serial traffic. A state directory that cannot be
    written must cost a stamp, not the bridge."""
    path = tmp_path / "blocked" / "osr2_serial_rx.txt"
    path.parent.write_text("", encoding="utf-8")  # a file where the directory should be
    stamp = ActivityStamp(path, wall_clock=lambda: 1711900000.0)

    stamp.mark()

    assert not path.exists()
