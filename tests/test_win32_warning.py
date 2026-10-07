"""The broker's half of the family's warning dialog: its identity and its icon."""
from __future__ import annotations

from unittest.mock import ANY, patch

import pytest
from PyQt6.QtWidgets import QApplication
from shared_ui.alert import Level
from shared_ui.palette import MAGENTA, PREVIEW_INK
from shared_ui.preview import Preview

from osr2_broker import win32


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_warning_is_the_familys_dialog_wearing_the_brokers_icon(qapp):
    with patch("shared_ui.alert.show_alert") as show_alert:
        win32.show_warning("OSR2 Broker", "Still going.", button_text="Got it", shown_as=None)

    show_alert.assert_called_once_with(
        "OSR2 Broker", "Still going.",
        level=Level.WARNING, icon=ANY, button_text="Got it",
    )
    assert _middle_of(show_alert.call_args.kwargs["icon"]) == MAGENTA


def test_the_button_says_ok_unless_the_caller_says_otherwise():
    with patch("shared_ui.alert.show_alert") as show_alert:
        win32.show_warning("OSR2 Broker", "Still going.", shown_as=None)

    assert show_alert.call_args.kwargs["button_text"] == "OK"


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
        win32.show_warning("OSR2 Broker", "Still going.", shown_as=None)

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
        win32.show_warning("OSR2 Broker", "Still going.", shown_as=Preview(feature="the new idle alert"))

    title, _message = show_alert.call_args.args
    assert title == "OSR2 Broker — preview of the new idle alert"
    assert _middle_of(show_alert.call_args.kwargs["icon"]) == PREVIEW_INK
    assert claimed == [f"{win32.APP_USER_MODEL_ID}.Preview"]
