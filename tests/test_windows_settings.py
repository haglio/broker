"""What the broker relies on Windows to keep, as its pyproject lists it.

``python -m app_support.windows_settings`` makes the machine match the list;
what is the broker's own about it is held here.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from app_support.launcher import launchers

from osr2_broker.win32 import APP_USER_MODEL_ID

REPO_ROOT = Path(__file__).resolve().parents[1]
LISTED = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["haglio"]


def test_what_the_list_starts_is_one_of_this_checkouts_launchers():
    declared = {launcher.file for launcher in launchers(REPO_ROOT)}

    assert {spec["launcher"] for spec in [*LISTED["shortcuts"].values(), *LISTED["scheduled-tasks"].values()]} <= declared


def test_the_icon_each_shortcut_shows_is_in_this_checkout():
    for spec in LISTED["shortcuts"].values():
        assert (REPO_ROOT / spec["icon"]).is_file(), spec["icon"]


def test_each_shortcut_carries_the_identity_the_app_claims():
    assert {spec["app-id"] for spec in LISTED["shortcuts"].values()} == {APP_USER_MODEL_ID}


def test_a_tray_that_died_is_started_again_within_two_minutes():
    task = LISTED["scheduled-tasks"]["OSR2 Broker"]

    assert (task["launcher"], task["every-minutes"]) == ("launch_broker_tray.vbs", 2)
