"""What launch_broker_tray.vbs runs, asked of the launcher under the real script host.

The "OSR2 Broker" scheduled task, the pinned shortcut and Fun Time all start
the tray through this file, so its name and place are pinned here.  It is
rendered from its spec in pyproject.toml by app_support.launcher, whose own tests
hold what every launcher does; what is the broker's is asked of this one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import assert_launchers_match_their_specs, dry_run

from osr2_broker import branch_session

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "launch_broker_tray.vbs"
PREVIEW_LAUNCHER = REPO_ROOT / "launch_preview_branch.vbs"

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


@on_windows
def test_a_preview_runs_this_worktree_s_tray_on_the_everyday_broker():
    """The everyday checkout's config, so the preview watches the broker that
    is running rather than starting a second one on the same serial port."""
    report = dry_run(PREVIEW_LAUNCHER)

    primary = REPO_ROOT.parents[2]
    assert Path(report.value("interpreter")) == primary / ".venv" / "Scripts" / "pythonw.exe"
    assert Path(report.value("directory")) == REPO_ROOT
    assert report.value("arguments") == (
        f'-m osr2_broker.tray --config "{primary / "osr2_broker_config.json"}"')
    assert report.values("environment") == [f"{branch_session.FLAG}=1"]
    assert Path(report.value("log")) == REPO_ROOT / "state" / "preview_branch.log"
