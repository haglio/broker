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


@on_windows
def test_the_tray_runs_with_this_checkouts_config():
    assert dry_run(LAUNCHER).value("arguments") == (
        f'-m osr2_broker.tray --config "{REPO_ROOT / "osr2_broker_config.json"}"')


@on_windows
def test_the_pinned_shortcut_starts_the_same_tray_with_the_loading_screen_up_from_the_click():
    tray, clicked = dry_run(LAUNCHER), dry_run(SHORTCUT_LAUNCHER)

    assert clicked.value("interpreter") == tray.value("interpreter")
    assert clicked.value("arguments") == tray.value("arguments")
    assert "app_support.loading_screen" in clicked.value("loading screen")
    assert tray.values("loading screen") == []


@on_windows
def test_a_preview_watches_the_broker_that_is_running_rather_than_starting_a_second_on_the_same_serial_port():
    report = dry_run(PREVIEW_LAUNCHER)

    assert report.value("arguments") == (
        f'-m osr2_broker.tray --config "{REPO_ROOT.parents[2] / "osr2_broker_config.json"}"')
    assert report.values("environment") == [f"{branch_session.FLAG}=1"]
