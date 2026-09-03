"""The launch smoke test: everything the tray launch imports, imported.

The suite can be entirely green while nothing appears in the notification area,
and this is the gap. The scheduled task, the Start Menu shortcut and fun_time
all start the broker the same way -- ``launch_broker_tray.vbs`` running
``pythonw -m osr2_broker.tray`` -- and ``main()`` there reaches the config, the
logging setup and the icon through imports *inside* the function, so a break in
any of them never touches a test that imports ``osr2_broker.tray`` and stops at
module level. The tray then spawns the broker itself as ``-m osr2_broker.app``,
so that module is on the same launch path.

``pythonw`` is what makes this invisible rather than merely broken: it has no
console, so an import that fails writes its traceback nowhere at all and the
tray icon simply never shows up.

So this drives the launch's import phase the way the launcher does: a fresh
interpreter, this repo as the working directory, no inherited ``PYTHONPATH``.

The walk that reads those imports off the AST and the three assertions that
replay them are ``app_support.launch_smoke``: seven repos carried a copy of the
same 200 lines, drifting. What stays here is the half that is this app's --
which files the launch executes, and how its launcher starts an interpreter.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_support.launch_smoke import (
    assert_an_unresolvable_import_is_caught,
    assert_every_import_resolves,
    assert_the_walk_reached,
    launch_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "osr2_broker"
LAUNCHER = REPO_ROOT / "launch_broker_tray.vbs"

# ``-m osr2_broker.tray`` runs tray.py, which is both the entrypoint and the
# module holding main(); it spawns the broker as ``-m osr2_broker.app``, whose
# own entrypoint is __main__.py.
LAUNCH_FILES = (
    REPO_ROOT / PACKAGE / "tray.py",
    REPO_ROOT / PACKAGE / "__main__.py",
    REPO_ROOT / PACKAGE / "app.py",
)

# Reached only from inside a main(), so a module-level import test never saw
# them. Asserted present, so a walk that silently found nothing -- a renamed
# file, a parse that returned an empty tree -- cannot pass as a clean launch.
_REACHED_ONLY_FROM_INSIDE_MAIN = (
    "osr2_broker.config",
    "osr2_broker.win32",
    "osr2_broker.monitor",
)


def _run_the_launchs_way(statements: list[str]) -> subprocess.CompletedProcess:
    """Run them the way ``launch_broker_tray.vbs`` runs the tray.

    The launcher sets this repo as the working directory and runs the venv's
    pythonw with nothing else, so the working directory is the whole path story
    -- any ``PYTHONPATH`` a developer or pytest happens to be carrying is
    dropped, because the scheduled task does not get it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"

    return subprocess.run(
        [sys.executable, "-c", "\n".join(statements)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_launch_imports_everything_it_names():
    """Failing here means no tray icon and no explanation: pythonw has no
    console, so the traceback from a failed import goes nowhere."""
    assert_every_import_resolves(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES))


def test_the_walk_reaches_the_imports_buried_in_main():
    """The guard above is only worth anything if the walk found the lazy ones --
    which is where the config, the icon and the shutdown guard are."""
    assert_the_walk_reached(
        launch_imports(PACKAGE, LAUNCH_FILES), _REACHED_ONLY_FROM_INSIDE_MAIN)


def test_a_launch_import_that_cannot_resolve_fails_here():
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    assert_an_unresolvable_import_is_caught(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES),
        "osr2_broker.config")


def test_the_launcher_runs_the_tray_from_this_repo_on_its_own_venv():
    """A python off PATH misses the editable siblings the tray imports and dies
    while importing -- which under pythonw is a launch that leaves no trace at
    all. The working directory is what this test's ``cwd`` mirrors, so a
    launcher that stopped setting it would leave this checking a fiction."""
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")

    assert ".venv\\Scripts\\pythonw.exe" in text
    assert "-m osr2_broker.tray" in text
    assert "shell.CurrentDirectory = projectRoot" in text
