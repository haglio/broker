"""Tests for the show_warning dark-themed dialog."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QPushButton
from shared_ui.colors import BG_TERTIARY, TEXT_SECONDARY


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_dialog_has_correct_title_and_message(qapp):
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        from osr2_broker.win32 import show_warning

        # Capture the dialog before exec is called
        created = {}

        original_init = QDialog.__init__

        def spy_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created["dlg"] = self

        with patch.object(QDialog, "__init__", spy_init):
            show_warning("Test Title", "Test message", button_text="Got it")

        dlg = created["dlg"]
        assert dlg.windowTitle() == "Test Title"
        labels = dlg.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        assert "Test message" in texts


def test_button_has_custom_text(qapp):
    created = {}
    original_init = QDialog.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created["dlg"] = self

    with (
        patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted),
        patch.object(QDialog, "__init__", spy_init),
    ):
        from osr2_broker.win32 import show_warning
        show_warning("Title", "Msg", button_text="I don't know, did you?")

    btns = created["dlg"].findChildren(QPushButton)
    assert any(b.text() == "I don't know, did you?" for b in btns)


def test_stylesheet_uses_dark_theme_colors(qapp):
    created = {}
    original_init = QDialog.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created["dlg"] = self

    with (
        patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted),
        patch.object(QDialog, "__init__", spy_init),
    ):
        from osr2_broker.win32 import show_warning
        show_warning("Title", "Msg")

    ss = created["dlg"].styleSheet()
    assert BG_TERTIARY.name() in ss
    assert TEXT_SECONDARY.name() in ss
