from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes

from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import try_acquire_mutex
from PyQt6.QtCore import QTimer

from .config import PROJECT_DIR
from .process_names import NAMER
from .single_instance import MUTEX_TRAY

FLAG = "BROKER_BRANCH_SESSION"
HAND_BACK_AFTER_MINUTES = 60
PATIENCE_SECONDS = 10.0
_RETRY_SECONDS = 0.2

_close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
_close_handle.argtypes = [ctypes.c_void_p]
_close_handle.restype = wintypes.BOOL


def take_the_flag() -> bool:
    return os.environ.pop(FLAG, None) == "1"


def branch() -> str:
    done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=PROJECT_DIR,
                          capture_output=True, text=True, check=False,
                          **hidden_subprocess_kwargs())
    return done.stdout.strip() or PROJECT_DIR.name


def app_name(preview: bool) -> str:
    return f"OSR2 Broker — preview of {branch()}" if preview else "OSR2 Broker"


def take_the_tray_over(*, claim=try_acquire_mutex, end_the_other_trays,
                       sleep=time.sleep, clock=time.monotonic) -> int | None:
    deadline = clock() + PATIENCE_SECONDS
    while (handle := claim(MUTEX_TRAY)) is None:
        if clock() >= deadline:
            return None
        end_the_other_trays()
        sleep(_RETRY_SECONDS)
    return handle


def end_the_other_trays() -> None:
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
            "Get-CimInstance Win32_Process | Where-Object { "
            f"$_.Name -match '{NAMER.process_name_pattern}' -and "
            "$_.CommandLine -match 'osr2_broker\\.tray' -and "
            f"$_.ProcessId -ne {os.getpid()} -and "
            f"$_.ProcessId -ne {os.getppid()} "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
            "-ErrorAction SilentlyContinue }",
        ],
        check=False,
        **hidden_subprocess_kwargs(),
    )


def let_go_of(claim: int) -> None:
    _close_handle(claim)


def start_the_usual_tray(config) -> None:
    environment = {key: value for key, value in os.environ.items() if key != FLAG}
    subprocess.Popen(["wscript.exe", str(config.project_dir / "launch_broker_tray.vbs")],
                     cwd=str(config.project_dir), env=environment,
                     **hidden_subprocess_kwargs())


def hand_back(config, claim: int, *, release=let_go_of,
              start_the_usual_tray=start_the_usual_tray) -> None:
    release(claim)
    start_the_usual_tray(config)


def hand_back_later(quit_the_preview) -> QTimer:
    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(HAND_BACK_AFTER_MINUTES * 60_000)
    timer.timeout.connect(quit_the_preview)
    timer.start()
    return timer
