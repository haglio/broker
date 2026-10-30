"""What the broker's launchers run, asked of each under the real script host.

The scheduled task and Fun Time start the tray through launch_broker_tray.vbs,
and the pinned shortcut through launch_broker_from_its_shortcut.vbs, so their
names and places are pinned here.  Each is
rendered from its spec in pyproject.toml by app_support.launcher, whose own tests
hold what every launcher does, and the family's gates hold that each is what its
spec renders; what is the broker's is asked of this one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app_support.launcher import dry_run

from osr2_broker import branch_session

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "launch_broker_tray.vbs"
SHORTCUT_LAUNCHER = REPO_ROOT / "launch_broker_from_its_shortcut.vbs"
PREVIEW_LAUNCHER = REPO_ROOT / "launch_preview_branch.vbs"

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


def test_the_launchers_are_where_the_scheduled_task_and_the_pin_point():
    assert LAUNCHER.is_file()
    assert SHORTCUT_LAUNCHER.is_file()


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
def test_the_pinned_shortcut_starts_the_same_tray_with_the_loading_screen_up_from_the_click():
    tray, clicked = dry_run(LAUNCHER), dry_run(SHORTCUT_LAUNCHER)

    assert clicked.value("interpreter") == tray.value("interpreter")
    assert clicked.value("arguments") == tray.value("arguments")
    assert "app_support.loading_screen" in clicked.value("loading screen")
    assert tray.values("loading screen") == []


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


@on_windows
def test_a_new_previews_first_click_shows_the_pictures_an_earlier_preview_left():
    report = dry_run(PREVIEW_LAUNCHER)

    primary = REPO_ROOT.parents[2]
    assert Path(report.value("pictures")) == primary / "state" / "preview_branch.screen" / "preview"
