"""The window a direct write leaves open.

A sender's T-Code and a fired hold both drive the OSR2 straight, bypassing MFP.
Either way the device has just been told where to go, and MFP's own stream has
to be dropped for a moment rather than allowed to argue with it.
"""
from __future__ import annotations

from osr2_broker.tcode_window import TCodeWriteWindow


def test_a_fresh_window_is_shut():
    """Nothing has written directly yet, so MFP is the only voice and is heard."""
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    assert window.is_open() is False


def test_marking_opens_the_window():
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    window.mark()

    assert window.is_open() is True


def test_the_window_shuts_once_the_suppression_time_has_passed():
    """The other side of the same comparison: a direct write mutes MFP for a
    moment, not for the rest of the session."""
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
    """Both bounds as literals rather than off SUPPRESS_SECONDS, which measures
    the constant against itself and leaves it free to move. Too short and MFP
    argues with the line that just landed; too long and MFP is silenced by a
    device its sender has stopped driving."""
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()

    clock[0] = 10.49
    assert window.is_open() is True

    clock[0] = 10.5
    assert window.is_open() is False
