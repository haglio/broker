from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from shared_ui import loading_process
from shared_ui.loading_window import Loading, LoadingCanceled
from shared_ui.preview import taskbar_identity

from osr2_broker import tray as tray_module
from osr2_broker.win32 import APP_USER_MODEL_ID, ICON_PATH


class _Loading:
    def __init__(self, happened: list[str], *, canceled: bool = False):
        self._happened = happened
        self._canceled = canceled

    def say(self, step: str) -> None:
        self._happened.append(f"said {step}")
        if self._canceled:
            raise LoadingCanceled

    def done(self) -> None:
        self._happened.append("done")


def _start_the_tray(qapp, cfg_path, *, canceled: bool = False) -> tuple[int, list[str]]:
    happened: list[str] = []
    tray = MagicMock()
    tray.show.side_effect = lambda: happened.append("tray shown")

    def built(*_args, **_kwargs):
        happened.append("tray built")
        return tray, MagicMock(), None

    with patch.object(tray_module, "configure_logging", return_value=logging.getLogger("test.tray")), \
         patch.object(tray_module, "install_exception_logging"), \
         patch.object(tray_module, "_name_this_process"), \
         patch.object(tray_module, "try_acquire_mutex", return_value=7), \
         patch.object(tray_module.peer_watch, "clear_broker_stand_down"), \
         patch.object(tray_module, "claim_taskbar_identity"), \
         patch.object(Loading, "at_the_click", return_value=_Loading(happened, canceled=canceled)), \
         patch.object(tray_module, "start_the_tray", side_effect=built), \
         patch.object(type(qapp), "exec", return_value=0):
        exit_code = tray_module.main(["--config", str(cfg_path)])
    return exit_code, happened


def test_the_loading_screen_walks_the_trays_start_and_goes_once_the_tray_shows(qapp, cfg_path):
    exit_code, happened = _start_the_tray(qapp, cfg_path)

    assert exit_code == 0
    assert happened == [*(f"said {step}" for step, _weight in tray_module.STEPS), "tray built", "tray shown", "done"]


def test_esc_on_the_loading_screen_starts_no_tray(qapp, cfg_path):
    exit_code, happened = _start_the_tray(qapp, cfg_path, canceled=True)

    assert exit_code == 0
    assert happened == [f"said {tray_module.STEPS[0][0]}"]


def test_the_loading_screen_runs_in_a_process_of_its_own_wearing_the_brokers_taskbar_button():
    with patch.object(loading_process.LoadingProcess, "open") as opened:
        tray_module.open_the_loading_screen(None)

    opened.assert_called_once_with(
        caption="Broker Loading", wordmark="Broker", icon=ICON_PATH, preview=None, steps=tray_module.STEPS,
        cancel_hint="Press Esc to cancel opening Broker", app_id=taskbar_identity(APP_USER_MODEL_ID, None))
