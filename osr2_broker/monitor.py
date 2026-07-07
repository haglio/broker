from __future__ import annotations

import json
from enum import Enum, auto
from pathlib import Path
from typing import Callable

IN_USE_THRESHOLD = 30.0


class Action(Enum):
    IDLE_ALERT = auto()


REARM_SECONDS = 60.0


class MonitorState:
    def __init__(self, idle_threshold: float = 900.0, rx_stale_threshold: float = 30.0,
                 rearm_seconds: float = REARM_SECONDS, idle_since: float | None = None,
                 alerted: bool = False):
        self._idle_threshold = idle_threshold
        self._rx_stale_threshold = rx_stale_threshold
        self._rearm_seconds = rearm_seconds
        self._device_on = False
        self._device_on_since: float | None = None
        self._idle_since: float | None = idle_since
        self._alerted = alerted
        self._warning_pending = False
        self._in_use_since: float | None = None

    @property
    def device_on(self) -> bool:
        return self._device_on

    @property
    def idle_since(self) -> float | None:
        return self._idle_since

    @property
    def alerted(self) -> bool:
        return self._alerted

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


def run_monitor_poll(
    state: MonitorState,
    *,
    now: float,
    last_rx: float | None,
    last_tx: float | None,
    auto_active: bool,
    idle_state_file: Path,
    on_alert: Callable[[], None],
) -> Action | None:
    """Advance the monitor one tick, persist the idle state so the 15-min
    countdown survives a broker restart, and dispatch the idle alert."""
    action = state.update(now, last_rx, last_tx, auto_active)
    save_idle_state(idle_state_file, state.idle_since, state.alerted)
    if action == Action.IDLE_ALERT:
        on_alert()
    return action


def read_timestamp(path: Path) -> float | None:
    try:
        return float(path.read_text().strip())
    except (OSError, ValueError):
        return None


def save_idle_state(path: Path, idle_since: float | None, alerted: bool) -> None:
    try:
        path.write_text(
            json.dumps({"idle_since": idle_since, "alerted": alerted}),
            encoding="utf-8",
        )
    except OSError:
        pass


def load_idle_state(path: Path) -> tuple[float | None, bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        idle_since = data["idle_since"]
        idle_since = float(idle_since) if idle_since is not None else None
        return idle_since, bool(data["alerted"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, False
