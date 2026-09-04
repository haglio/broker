"""The broker's half of the family's warning dialog: its identity and its icon."""
from __future__ import annotations

from unittest.mock import patch

from shared_ui.alert import Level

from osr2_broker import win32


def test_the_warning_is_the_familys_dialog_wearing_the_brokers_icon():
    with patch("shared_ui.alert.show_alert") as show_alert:
        win32.show_warning("OSR2 Broker", "Still going.", button_text="Got it")

    show_alert.assert_called_once_with(
        "OSR2 Broker", "Still going.",
        level=Level.WARNING, icon=win32.ICON_PATH, button_text="Got it",
    )


def test_the_button_says_ok_unless_the_caller_says_otherwise():
    with patch("shared_ui.alert.show_alert") as show_alert:
        win32.show_warning("OSR2 Broker", "Still going.")

    assert show_alert.call_args.kwargs["button_text"] == "OK"


def test_the_process_claims_its_taskbar_identity_before_the_dialog_appears():
    """Windows reads the identity when a window of this process first appears,
    so claiming it after the dialog is up is claiming it too late."""
    order = []

    with (
        patch.object(
            win32, "_SetCurrentProcessExplicitAppUserModelID",
            side_effect=lambda aumid: order.append(aumid),
        ),
        patch("shared_ui.alert.show_alert", side_effect=lambda *a, **k: order.append("dialog")),
    ):
        win32.show_warning("OSR2 Broker", "Still going.")

    assert order == [win32.APP_USER_MODEL_ID, "dialog"]
