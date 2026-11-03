from __future__ import annotations

from unittest.mock import patch

from osr2_broker import win32


def test_the_window_holding_up_a_shutdown_is_titled_broker():
    with (
        patch.object(win32, "_RegisterClassW"),
        patch.object(win32, "_CreateWindowExW") as create_window,
        patch.object(win32, "_SetTimer"),
        patch.object(win32, "_GetMessageW", return_value=0),
    ):
        win32.ShutdownGuard(
                should_block_fn=lambda: False, poll_fn=lambda: None,
                poll_interval_ms=1000, block_reason="Made up.",
            ).run()

    _style, _class_name, title, *_rest = create_window.call_args.args
    assert title == "Broker"


def test_a_refused_taskbar_identity_is_logged_and_the_launch_goes_on(caplog):
    def refuse(_identity):
        raise OSError("refused")

    win32.claim_taskbar_identity(None, set_identity=refuse)

    assert "Could not claim the taskbar identity" in caplog.text
