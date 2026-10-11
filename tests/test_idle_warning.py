from __future__ import annotations

import subprocess
import sys
from unittest.mock import ANY, patch

import pytest
from PyQt6.QtWidgets import QApplication
from shared_ui.alert import Level
from shared_ui.palette import MAGENTA, PREVIEW_INK
from shared_ui.preview import Preview, preview_of

from osr2_broker import idle_warning, win32
from osr2_broker.config import PROJECT_DIR, load_config


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _closed(argv, **_kwargs):
    return subprocess.CompletedProcess(argv, 0, "", "")


def test_the_warning_is_shown_by_a_process_of_its_own(cfg_path):
    config = load_config(str(cfg_path))
    started = []

    idle_warning.show_until_closed(
        config, run=lambda argv, **kwargs: started.append((argv, kwargs)) or _closed(argv))

    (argv, kwargs), = started
    assert argv == [sys.executable, "-m", "osr2_broker.idle_warning",
                    "--config", str(config.config_path)]
    assert kwargs["cwd"] == PROJECT_DIR


def test_the_warnings_process_gets_no_console_and_is_not_told_to_start_hidden(cfg_path):
    """A hidden start would hide the dialog itself: Windows shows a process's
    first window the way its STARTUPINFO says to."""
    config = load_config(str(cfg_path))
    started = []

    idle_warning.show_until_closed(
        config, run=lambda argv, **kwargs: started.append(kwargs) or _closed(argv))

    (kwargs,) = started
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert "startupinfo" not in kwargs


def test_what_the_warnings_process_says_comes_back_as_text(cfg_path):
    config = load_config(str(cfg_path))
    started = []

    idle_warning.show_until_closed(
        config, run=lambda argv, **kwargs: started.append(kwargs) or _closed(argv))

    (kwargs,) = started
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["errors"] == "replace"


def test_the_warning_asks_whether_he_forgot_to_turn_the_osr2_off(cfg_factory):
    config_path = cfg_factory({"idle_minutes": 20.0})

    with patch.object(idle_warning, "show_warning") as shown:
        assert idle_warning.main(["--config", str(config_path)]) == 0

    shown.assert_called_once_with(
        "OSR2 Broker",
        "Your OSR2 has been idle for 20 minutes.\nDid you forget to turn it off?",
        button_text="I don't know, did you?",
        shown_as=preview_of(PROJECT_DIR),
    )


def test_the_warning_is_the_familys_dialog_wearing_the_brokers_icon(qapp):
    with patch("shared_ui.alert.show_alert") as show_alert:
        idle_warning.show_warning("OSR2 Broker", "Still going.", button_text="Got it",
                                  shown_as=None)

    show_alert.assert_called_once_with(
        "OSR2 Broker", "Still going.",
        level=Level.WARNING, icon=ANY, button_text="Got it",
    )
    assert _middle_of(show_alert.call_args.kwargs["icon"]) == MAGENTA


def test_the_process_claims_its_taskbar_identity_before_the_dialog_appears():
    """Windows reads the identity when a window of this process first appears,
    so claiming it after the dialog is up is claiming it too late."""
    order = []

    with (
        patch.object(
            win32, "set_app_user_model_id",
            side_effect=lambda aumid: order.append(aumid),
        ),
        patch("shared_ui.alert.show_alert", side_effect=lambda *a, **k: order.append("dialog")),
    ):
        idle_warning.show_warning("OSR2 Broker", "Still going.", button_text="Got it",
                                  shown_as=None)

    assert order == [win32.APP_USER_MODEL_ID, "dialog"]


def _middle_of(icon):
    middle = icon.pixmap(256, 256).toImage().pixelColor(128, 128)
    return middle.red(), middle.green(), middle.blue()


def test_a_previews_warning_names_the_feature_it_demos_and_wears_the_preview_ink(qapp):
    claimed = []
    with (
        patch.object(win32, "set_app_user_model_id", side_effect=claimed.append),
        patch("shared_ui.alert.show_alert") as show_alert,
    ):
        idle_warning.show_warning("OSR2 Broker", "Still going.", button_text="Got it",
                                  shown_as=Preview(feature="the new idle alert"))

    title, _message = show_alert.call_args.args
    assert title == "OSR2 Broker — preview of the new idle alert"
    assert _middle_of(show_alert.call_args.kwargs["icon"]) == PREVIEW_INK
    assert claimed == [f"{win32.APP_USER_MODEL_ID}.Preview"]
