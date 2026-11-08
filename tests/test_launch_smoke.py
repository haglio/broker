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

LAUNCH_FILES = (
    REPO_ROOT / PACKAGE / "tray.py",
    REPO_ROOT / PACKAGE / "__main__.py",
    REPO_ROOT / PACKAGE / "app.py",
    REPO_ROOT / PACKAGE / "idle_warning.py",
)

_REACHED_ONLY_INSIDE_A_FUNCTION = (
    "shared_ui.alert",
    "shared_ui.loading_process",
)


def _run_the_launchs_way(statements: list[str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"

    return subprocess.run(
        [sys.executable, "-c", "\n".join(statements)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_launch_imports_everything_it_names_under_pythonw_a_failed_import_shows_nothing_the_tray_icon_never_appears():
    assert_every_import_resolves(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES))


def test_the_walk_reaches_the_imports_buried_in_functions():
    assert_the_walk_reached(
        launch_imports(PACKAGE, LAUNCH_FILES), _REACHED_ONLY_INSIDE_A_FUNCTION)


def test_a_launch_import_that_cannot_resolve_fails_here():
    assert_an_unresolvable_import_is_caught(
        _run_the_launchs_way, launch_imports(PACKAGE, LAUNCH_FILES),
        "osr2_broker.config")
