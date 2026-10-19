"""The mute that outlasts a direct write.

T-Code from a sender and a fired hold both reach the OSR2 bypassing MFP. Both
are "someone drove the device directly just now", which is what MFP's forwarder
has to know: two writers fighting over one serial port make the device stutter
between them, so the window says whose turn it is not.
"""
from __future__ import annotations


class TCodeWriteWindow:
    """How recently T-Code went straight to the OSR2, bypassing MFP."""

    SUPPRESS_SECONDS = 0.5

    def __init__(self, *, monotonic):
        self._monotonic = monotonic
        self._last = 0.0

    def mark(self) -> None:
        self._last = self._monotonic()

    def is_open(self) -> bool:
        return self._last > 0.0 and (self._monotonic() - self._last) < self.SUPPRESS_SECONDS
