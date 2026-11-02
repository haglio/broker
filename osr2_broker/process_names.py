"""What the broker's two processes are called in the Windows task list.

Both run as ``pythonw.exe``, so both arrived as anonymous "Python" rows -- and a
supervisor and the thing it supervises being indistinguishable is exactly the
pair you need to tell apart when one of them is stuck.  Windows takes what it
shows about a process from the file it was started from, so each starts through
a copy of the interpreter named, described and marked for its part.

The tray cannot name itself on the way in -- writing the copy takes the very
interpreter being named -- so it prepares its own for the next launch and
``launch_broker_tray.vbs`` picks it up.  The broker is a child, so the tray
names it outright when it launches it.

The sweep that kills a broker matches on image name, so it reads this too: a
broker running under a name the sweep does not know is a broker nothing can
stop.
"""
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
