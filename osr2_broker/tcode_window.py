from __future__ import annotations


class TCodeWriteWindow:
    SUPPRESS_SECONDS = 0.5

    def __init__(self, *, monotonic):
        self._monotonic = monotonic
        self._last = 0.0

    def mark(self) -> None:
        self._last = self._monotonic()

    def is_open(self) -> bool:
        return self._last > 0.0 and (self._monotonic() - self._last) < self.SUPPRESS_SECONDS
