"""Tests for the broker's system tray icon and its watchdog."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication
from shared_ui.colors import BG_TERTIARY


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_menu_is_painted_in_the_shared_dark_palette(qapp):
    """The menu must render dark, not in Windows' default light chrome."""
    from osr2_broker.tray import build_menu

    menu = build_menu()
    menu.resize(menu.sizeHint())
    image = menu.grab().toImage()

    # Sample inside the menu body, clear of the rounded corners and border.
    pixel = image.pixelColor(image.width() // 2, image.height() // 2)
    assert pixel.name() == BG_TERTIARY.name()


def _brightest_text_pixel(image, rect):
    """The lightest pixel in a menu row — its text, against the dark fill."""
    return max(
        max(image.pixelColor(x, y).getRgb()[:3])
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )


def test_the_status_line_reads_as_a_label_not_a_command(qapp):
    """It is disabled, so it must look dimmer than the items you can click."""
    from osr2_broker.tray import BrokerTray

    tray = BrokerTray()
    menu = tray.contextMenu()
    menu.resize(menu.sizeHint())
    image = menu.grab().toImage()

    status = _brightest_text_pixel(image, menu.actionGeometry(tray.status_action))
    command = _brightest_text_pixel(image, menu.actionGeometry(tray.start_action))
    assert status < command


def test_the_item_under_the_cursor_lights_up(qapp):
    """Without an explicit rule the stylesheet flattens Qt's own highlight."""
    from shared_ui.colors import BG_BUTTON
    from osr2_broker.tray import BrokerTray

    tray = BrokerTray()
    menu = tray.contextMenu()
    menu.resize(menu.sizeHint())
    menu.setActiveAction(tray.start_action)
    image = menu.grab().toImage()

    row = menu.actionGeometry(tray.start_action)
    fill = image.pixelColor(row.right() - 2, row.center().y())
    assert fill.name() == BG_BUTTON.name()


def test_tray_menu_offers_the_broker_controls(qapp):
    from osr2_broker.tray import BrokerTray

    tray = BrokerTray()

    labels = [a.text() for a in tray.contextMenu().actions() if not a.isSeparator()]
    assert labels == [
        "Broker status: unknown",
        "Start broker",
        "Pause broker",
        "Open broker log",
        "Quit",
    ]


@pytest.mark.parametrize(
    "written, expected",
    [
        ("0", "control"),
        ("1", "auto"),
        ("2", "stale-timeout"),
        ("﻿1\r\n", "auto"),
        ("7", "mode=7"),
    ],
)
def test_mode_text_names_the_mode_the_broker_wrote(tmp_path, written, expected):
    from osr2_broker.tray import mode_text

    mode_file = tmp_path / "genau_mode.txt"
    mode_file.write_text(written, encoding="utf-8")

    assert mode_text(mode_file) == expected


def test_mode_text_is_unknown_when_the_broker_has_written_nothing(tmp_path):
    from osr2_broker.tray import mode_text

    assert mode_text(tmp_path / "genau_mode.txt") == "unknown"


def test_supervisor_reads_liveness_from_the_broker_s_own_mutex(cfg_path):
    from osr2_broker.config import load_config
    from osr2_broker.single_instance import MUTEX_BROKER, mutex_name_for_config
    from osr2_broker.tray import BrokerSupervisor

    config = load_config(cfg_path)
    probed = []
    supervisor = BrokerSupervisor(
        config,
        launch=lambda argv: None,
        terminate=lambda: None,
        is_held=lambda name: probed.append(name) or True,
    )

    assert supervisor.is_running()
    assert probed == [mutex_name_for_config(MUTEX_BROKER, config.config_path)]


def _supervisor(cfg_path, *, running=False):
    """A supervisor over a real config, with its launch/kill seams recorded."""
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerSupervisor

    calls = {"launched": [], "terminated": 0}

    def terminate():
        calls["terminated"] += 1

    supervisor = BrokerSupervisor(
        load_config(cfg_path),
        launch=calls["launched"].append,
        terminate=terminate,
        is_held=lambda name: running,
    )
    return supervisor, calls


def test_start_runs_the_broker_module_against_our_config(cfg_path):
    import sys

    from osr2_broker.process_names import BROKER_ROLE, NAMER

    supervisor, calls = _supervisor(cfg_path, running=False)

    supervisor.start()

    # Through the copy named for the broker rather than the bare interpreter, so
    # the task list can tell it from the tray supervising it -- see
    # osr2_broker.process_names.  named_exe falls back to the interpreter it was
    # handed when the copy cannot be made, so this holds either way.
    assert calls["launched"] == [
        [NAMER.named_exe(sys.executable, BROKER_ROLE), "-m", "osr2_broker.app",
         "--config", str(cfg_path)],
    ]


def test_start_leaves_a_live_broker_alone(cfg_path):
    supervisor, calls = _supervisor(cfg_path, running=True)

    supervisor.start()

    assert calls["launched"] == []


def test_restart_replaces_a_live_broker(cfg_path):
    supervisor, calls = _supervisor(cfg_path, running=True)

    supervisor.restart()

    assert calls["terminated"] == 1
    assert len(calls["launched"]) == 1


def test_stop_kills_the_broker_without_starting_another(cfg_path):
    supervisor, calls = _supervisor(cfg_path, running=True)

    supervisor.stop()

    assert calls["terminated"] == 1
    assert calls["launched"] == []


class FakeSupervisor:
    """Records what the watchdog asked of the broker."""

    def __init__(self, running=False):
        self.running = running
        self.starts = 0
        self.stops = 0
        self.restarts = 0

    def is_running(self):
        return self.running

    def start(self):
        # Idempotent, like the real supervisor: a live broker is left alone.
        if self.running:
            return
        self.starts += 1
        self.running = True

    def stop(self):
        self.stops += 1
        self.running = False

    def restart(self):
        self.restarts += 1
        self.running = True


@pytest.fixture()
def tray(qapp):
    from osr2_broker.tray import BrokerTray

    return BrokerTray()


def test_watchdog_revives_a_dead_broker(tray, cfg_path):
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    supervisor = FakeSupervisor(running=False)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.tick()

    assert supervisor.starts == 1


def test_watchdog_leaves_a_paused_broker_dead(tray, cfg_path):
    """Pause must survive the next tick, or the tray fights the user."""
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    supervisor = FakeSupervisor(running=True)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.pause()
    app.tick()

    assert supervisor.stops == 1
    assert supervisor.starts == 0


def test_starting_by_hand_clears_the_pause(tray, cfg_path):
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    supervisor = FakeSupervisor(running=False)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.pause()
    app.start_or_restart()
    app.tick()

    assert supervisor.starts == 1


def test_restart_from_the_menu_replaces_a_live_broker(tray, cfg_path):
    """On a running broker the menu says 'Restart broker', and it must mean it:
    because start() is idempotent, collapsing the restart branch into start()
    turns the menu item into a silent no-op — and until this test, nothing
    noticed (audit finding broker/all/tests/013)."""
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    supervisor = FakeSupervisor(running=True)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.start_or_restart()

    assert supervisor.restarts == 1
    assert supervisor.starts == 0


def test_a_failed_beat_does_not_stop_the_watchdog(tray, cfg_path):
    """The tray is the broker's only supervisor; one bad tick must not end it."""
    import logging

    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp, _guarded_tick

    class ExplodingSupervisor(FakeSupervisor):
        def is_running(self):
            raise OSError("WMI hiccup")

    app = BrokerTrayApp(load_config(cfg_path), ExplodingSupervisor(), tray)

    with pytest.raises(OSError):
        app.tick()

    _guarded_tick(app, logging.getLogger("test-watchdog"))


def test_opening_the_log_creates_it_first_so_the_editor_has_something(tray, cfg_path):
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    config = load_config(cfg_path)
    opened = []
    app = BrokerTrayApp(
        config, FakeSupervisor(), tray, open_file=opened.append,
    )

    app.open_log()

    log_path = config.log_file("broker")
    assert log_path.exists()
    assert opened == [log_path]


def test_quitting_takes_the_broker_down_with_the_tray(tray, cfg_path):
    """A surviving broker would be unsupervised — nothing left to restart it."""
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    supervisor = FakeSupervisor(running=True)
    quit_calls = []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.quit(quit_app=lambda: quit_calls.append(True))

    assert supervisor.stops == 1
    assert not tray.isVisible()
    assert quit_calls == [True]


def test_a_second_tray_stands_down(cfg_path):
    """The scheduled task relaunches the tray every couple of minutes."""
    import logging
    from unittest.mock import patch

    from app_support import logging_utils

    from osr2_broker import tray as tray_module

    # main() installs its process-wide scaffolding before it reaches the mutex
    # check, and none of it belongs to the rest of the session: both excepthooks
    # replaced by one that logs to the 'osr2_broker.tray' logger, a rotating file
    # handler on that logger pointed inside a state directory this test is about
    # to delete, and -- on Windows -- pythonw.exe copied into the live .venv and
    # stamped. tests/test_app.py patches the same three for the broker's own
    # main(); main() imports these two inside the function, so they are patched
    # where they are defined.
    with patch.object(logging_utils, "configure_logging",
                      return_value=logging.getLogger("test.tray")), \
         patch.object(logging_utils, "install_exception_logging"), \
         patch.object(tray_module, "_name_this_process"), \
         patch.object(tray_module, "try_acquire_mutex", return_value=None) as acquire:
        assert tray_module.main(["--config", str(cfg_path)]) == 0

    acquire.assert_called_once_with(tray_module.MUTEX_TRAY)


def test_tick_shows_the_broker_s_state_in_the_menu(tray, cfg_path):
    from osr2_broker.config import load_config
    from osr2_broker.tray import BrokerTrayApp

    config = load_config(cfg_path)
    config.genau_mode_file.write_text("1", encoding="utf-8")
    app = BrokerTrayApp(config, FakeSupervisor(running=True), tray)

    app.tick()

    assert tray.status_action.text() == "Broker status: running (auto)"


def test_running_broker_offers_a_restart_and_a_live_pause(qapp):
    from osr2_broker.tray import BrokerTray

    tray = BrokerTray()
    tray.set_status(running=True, mode="auto")

    assert tray.status_action.text() == "Broker status: running (auto)"
    assert tray.start_action.text() == "Restart broker"
    assert tray.pause_action.isEnabled()
    assert tray.toolTip() == "OSR2 Broker: running (auto)"


def test_stopped_broker_offers_a_start_and_a_dead_pause(qapp):
    from osr2_broker.tray import BrokerTray

    tray = BrokerTray()
    tray.set_status(running=False, mode="unknown")

    assert tray.status_action.text() == "Broker status: stopped"
    assert tray.start_action.text() == "Start broker"
    assert not tray.pause_action.isEnabled()
    assert tray.toolTip() == "OSR2 Broker: stopped"
