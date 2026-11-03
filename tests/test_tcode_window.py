from __future__ import annotations

from osr2_broker.tcode_window import TCodeWriteWindow


def test_a_fresh_window_is_shut():
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    assert window.is_open() is False


def test_marking_opens_the_window():
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    window.mark()

    assert window.is_open() is True


def test_the_window_shuts_once_the_suppression_time_has_passed():
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()
    clock[0] += TCodeWriteWindow.SUPPRESS_SECONDS

    assert window.is_open() is False


def test_the_window_stays_open_to_the_last_moment():
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()
    clock[0] += TCodeWriteWindow.SUPPRESS_SECONDS - 0.001

    assert window.is_open() is True


def test_the_direct_write_window_is_half_a_second():
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()

    clock[0] = 10.49
    assert window.is_open() is True

    clock[0] = 10.5
    assert window.is_open() is False
