"""What launch_broker_tray.vbs runs, asked of the launcher under the real script host.

The "OSR2 Broker" scheduled task, the Start Menu shortcut and Fun Time all start
the tray through this file, so its name and place are pinned here.  It is
rendered from its spec in pyproject.toml by app_support.launcher, whose own tests
hold what every launcher does; what is the broker's is asked of this one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import assert_launchers_match_their_specs, dry_run

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "launch_broker_tray.vbs"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


def test_the_launcher_is_where_the_scheduled_task_points():
    assert LAUNCHER.is_file()


def test_the_launcher_is_what_its_spec_renders():
    assert_launchers_match_their_specs(REPO_ROOT)


@on_windows
def test_the_tray_runs_windowed_from_this_checkout_on_its_venv_with_its_config():
    """pythonw, not python: the tray is a GUI app and must not flash a console."""
    report = dry_run(LAUNCHER)

    assert Path(report.value("interpreter")).parent == REPO_ROOT / ".venv" / "Scripts"
    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == (
        f'-m osr2_broker.tray --config "{REPO_ROOT / "osr2_broker_config.json"}"')
    assert report.values("log") == []
