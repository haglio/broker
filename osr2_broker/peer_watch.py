from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app_support import peer_watch
from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import is_mutex_held

BROKER_KEY = "broker"
EVOLVER_KEY = "evolver"

# Unqualified, so Windows keeps it in the logon session's namespace, where Evolver runs.
EVOLVER_MUTEX = "EvolverTrayApp_SingleInstance"


def evolver_is_up(*, is_held=is_mutex_held) -> bool:
    return is_held(EVOLVER_MUTEX)


def launch_evolver(
    launcher: Path,
    logger: logging.Logger,
    *,
    popen=subprocess.Popen,
) -> None:
    if not launcher.is_file():
        return
    popen(["wscript.exe", str(launcher)], cwd=str(launcher.parent),
          **hidden_subprocess_kwargs())
    logger.info("Evolver was not running; started it from %s", launcher)


def watch_evolver(config, logger: logging.Logger, **kwargs) -> peer_watch.PeerWatch:
    return peer_watch.PeerWatch(
        peer_key=EVOLVER_KEY,
        is_up=evolver_is_up,
        launch=lambda: launch_evolver(config.evolver_launcher, logger),
        logger=logger,
        **kwargs,
    )


def stand_broker_down() -> None:
    peer_watch.stand_down(BROKER_KEY)


def clear_broker_stand_down() -> None:
    peer_watch.clear_stand_down(BROKER_KEY)
