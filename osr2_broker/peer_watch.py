"""The broker's half of the pair that keeps the broker and Evolver both up.

The broker is already supervised twice over: a scheduled task relaunches this
tray every couple of minutes, and the tray keeps the broker process alive. Its
neighbour Evolver has none of that. It starts from a Startup-folder shortcut and
that is the whole arrangement, so any death -- a crash, a kill from the task
list, the quit it performs on itself when Windows announces a session end that is
then cancelled -- leaves it down until the next sign-in, which its own log
records as outages of six hours, eight days, thirteen days.

So this tray watches Evolver too. That costs the broker nothing and hands Evolver
the supervisor it has never had: the scheduled task revives this tray, and this
tray revives Evolver. Evolver watches back, which covers the one thing the task
cannot -- the task itself being switched off.

Nothing is ever killed here. A launch over a live Evolver is absorbed by
Evolver's own single-instance mutex, so the worst a misread costs is a process
that exits immediately, where killing first could not be taken back. And a quit
the user asked for is left alone: see :mod:`app_support.peer_watch`, whose
stand-down marker both sides honor.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app_support import peer_watch
from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import is_mutex_held

# The two names this pair calls each other by. Strings rather than an import
# because the two apps share no code and never will; Evolver spells the same
# pair in its gui/peer_watch.py, and the two files are the only places either
# name appears.
BROKER_KEY = "broker"
EVOLVER_KEY = "evolver"

# Evolver holds this for as long as it is running -- one process, tray and
# scheduler together, so it answers the whole question. Unqualified, so it lives
# in the logon session's namespace rather than the machine's; this tray runs
# interactively in that same session, which is the only place Evolver ever runs.
EVOLVER_MUTEX = "EvolverTrayApp_SingleInstance"


def evolver_is_up(*, is_held=is_mutex_held) -> bool:
    """Whether Evolver is running."""
    return is_held(EVOLVER_MUTEX)


def launch_evolver(
    launcher: Path,
    logger: logging.Logger,
    *,
    popen=subprocess.Popen,
) -> None:
    """Start Evolver, hidden, unless there is no Evolver here to start.

    A missing launcher is the ordinary case rather than an error: a machine with
    no Evolver beside the broker has no peer, and the only effect of saying so
    would be a line in the log every fifteen minutes forever.
    """
    if not launcher.is_file():
        return
    popen(["wscript.exe", str(launcher)], cwd=str(launcher.parent),
          **hidden_subprocess_kwargs())
    logger.info("Evolver was not running; started it from %s", launcher)


def watch_evolver(config, logger: logging.Logger, **kwargs) -> peer_watch.PeerWatch:
    """The watch this tray keeps on Evolver, beaten by the tray's own watchdog.

    Both halves go in as lambdas so each beat looks the names up again rather
    than holding what they meant when the tray was built -- which is what lets a
    test stand in for either without reaching inside the watch.
    """
    return peer_watch.PeerWatch(
        peer_key=EVOLVER_KEY,
        is_up=lambda: evolver_is_up(),
        launch=lambda: launch_evolver(config.evolver_launcher, logger),
        logger=logger,
        **kwargs,
    )


def stand_broker_down() -> None:
    """Record that this quit was asked for, so Evolver leaves the broker down."""
    peer_watch.stand_down(BROKER_KEY)


def clear_broker_stand_down() -> None:
    """Forget any earlier stand-down. Being started at all is the user asking for this."""
    peer_watch.clear_stand_down(BROKER_KEY)
