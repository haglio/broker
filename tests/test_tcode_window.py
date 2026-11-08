from __future__ import annotations

from osr2_broker.tcode_window import TCodeWriteWindow


def test_a_fresh_window_is_shut():
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    assert window.is_open() is False


def test_a_direct_write_opens_the_window_in_which_mfp_is_dropped_two_writers_make_the_device_stutter():
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


def test_the_window_is_a_literal_half_second_shorter_lets_mfp_argue_with_the_line_longer_keeps_mfp_silent_after_the_sender_stopped():
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()

    clock[0] = 10.49
    assert window.is_open() is True

    clock[0] = 10.5
    assert window.is_open() is False
