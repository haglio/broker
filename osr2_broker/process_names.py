from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from app_support.process_identity import ProcessNamer
from app_support.subprocess_utils import hidden_subprocess_kwargs

PROJECT_DIR = Path(__file__).resolve().parent.parent

APP_NAME = "Broker"
TRAY_ROLE = "Tray"
BROKER_ROLE = "Broker"

# Windows takes a process's row in the task list from the file it was started from.
NAMER = ProcessNamer(APP_NAME, icon=PROJECT_DIR / "broker_icon.ico")


def end_the_processes_running(module: str, *, sparing: Iterable[int] = ()) -> None:
    matches = " -and ".join((
        f"$_.Name -match '{NAMER.process_name_pattern}'",
        f"$_.CommandLine -match '{re.escape(module)}'",
        *(f"$_.ProcessId -ne {pid}" for pid in sparing),
    ))
    sweep = (f"Get-CimInstance Win32_Process | Where-Object {{ {matches} }} | ForEach-Object "
             "{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", sweep],
        check=False,
        **hidden_subprocess_kwargs(),
    )
