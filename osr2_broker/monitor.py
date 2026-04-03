from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

IN_USE_THRESHOLD = 30.0


class Action(Enum):
    IDLE_ALERT = auto()


REARM_SECONDS = 60.0


class MonitorState:
    def __init__(self, idle_threshold: float = 900.0, rx_stale_threshold: float = 30.0,
                 rearm_seconds: float = REARM_SECONDS):
        self._idle_threshold = idle_threshold
        self._rx_stale_threshold = rx_stale_threshold
        self._rearm_seconds = rearm_seconds
        self._device_on = False
        self._device_on_since: float | None = None
        self._idle_since: float | None = None
        self._alerted = False
        self._warning_pending = False
        self._in_use_since: float | None = None

    @property
    def device_on(self) -> bool:
        return self._device_on

    def acknowledge(self) -> None:
        self._warning_pending = False

    def update(
        self,
        now: float,
        last_rx: float | None,
        last_tx: float | None,
        auto_mode: bool,
    ) -> Action | None:
        was_on = self._device_on
        self._device_on = last_rx is not None and (now - last_rx) < self._rx_stale_threshold
        in_use = auto_mode or (last_tx is not None and (now - last_tx) < IN_USE_THRESHOLD)

        if not self._device_on:
            self._device_on_since = None
            self._idle_since = None
            self._in_use_since = None
            return None

        if not was_on:
            self._device_on_since = now

        if in_use:
            self._idle_since = None
            if self._in_use_since is None:
                self._in_use_since = now
            if not self._alerted or (now - self._in_use_since) >= self._rearm_seconds:
                self._alerted = False
            return None
        else:
            self._in_use_since = None

        # Device on but not in use
        if self._idle_since is None:
            on_since = self._device_on_since or now
            if last_tx is not None and last_tx > on_since:
                self._idle_since = last_tx
            elif last_tx is not None:
                self._idle_since = on_since
            else:
                self._idle_since = now

        if not self._alerted and not self._warning_pending and (now - self._idle_since) >= self._idle_threshold:
            self._alerted = True
            self._warning_pending = True
            return Action.IDLE_ALERT

        return None


def read_timestamp(path: Path) -> float | None:
    try:
        return float(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_auto_mode(path: Path) -> bool:
    try:
        return path.read_text().strip() == "1"
    except OSError:
        return False
