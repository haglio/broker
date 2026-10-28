"""Tests for the broker's system tray icon and its watchdog."""
from __future__ import annotations

import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from app_support.file_channel import publish_stamp
from app_support.win32 import mutex_name
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QImage
from shared_ui.colors import BG_TERTIARY, BLUE, TEXT_SECONDARY
from shared_ui.icons import glyph_pixmap
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

from osr2_broker import branch_session
from osr2_broker import tray as tray_module
from osr2_broker.config import PROJECT_DIR, load_config
from osr2_broker.process_names import BROKER_ROLE, NAMER
from osr2_broker.single_instance import MUTEX_BROKER
from osr2_broker.tray import BrokerSupervisor, BrokerTray, BrokerTrayApp, _guarded_tick
from tests.heard import what_is_said_on


def test_menu_is_painted_in_the_shared_dark_palette(qapp):
    """The menu must render dark, not in Windows' default light chrome.

    The tray's own menu, with its rows: under the family's rules an empty menu
    has no width to sample.
    """

    tray = BrokerTray()
    menu = tray.contextMenu()
    menu.resize(menu.sizeHint())
    image = menu.grab().toImage()

    # Inside a row, at its far end: clear of the border, and of the row's text
    # whatever font the machine draws it in -- the middle of the menu landed on
    # a glyph on the gate's runner.
    row = menu.actionGeometry(tray.start_action)
    pixel = image.pixelColor(row.right() - 2, row.center().y())
    assert pixel.name() == BG_TERTIARY.name()


def _brightest_text_pixel(image, rect):
    """The lightest pixel in a menu row — its text, against the dark fill."""
    return max(
        max(image.pixelColor(x, y).getRgb()[:3])
        for y in range(rect.top(), rect.bottomLeft().y() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )


def test_the_status_line_reads_as_a_label_not_a_command(qapp):
    """It is disabled, so it must look dimmer than the items you can click."""

    tray = BrokerTray()
    menu = tray.contextMenu()
    menu.resize(menu.sizeHint())
    image = menu.grab().toImage()

    status = _brightest_text_pixel(image, menu.actionGeometry(tray.status_action))
    command = _brightest_text_pixel(image, menu.actionGeometry(tray.start_action))
    assert status < command


def test_the_item_under_the_cursor_lights_up(qapp):
    """Without an explicit rule the stylesheet flattens Qt's own highlight; the
    family's rule lights the row in the blue every menu in the family uses."""


    tray = BrokerTray()
    menu = tray.contextMenu()
    menu.resize(menu.sizeHint())
    menu.setActiveAction(tray.start_action)
    image = menu.grab().toImage()

    row = menu.actionGeometry(tray.start_action)
    fill = image.pixelColor(row.right() - 2, row.center().y())
    assert fill.name() == BLUE.name()


def test_tray_menu_offers_the_broker_controls_laid_out_as_the_evolver_s_are(qapp):
    """Its status ruled off above the commands, and the commands in the
    Evolver's capitals."""

    tray = BrokerTray()

    rows = ["---" if a.isSeparator() else a.text() for a in tray.contextMenu().actions()]
    assert rows == [
        "Broker status: unknown",
        "---",
        "Start Broker",
        "Pause Broker",
        "Open Broker Log",
        "---",
        "Quit",
    ]


def _drawn(icon: QIcon) -> QImage:
    return icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()


def _family_mark(name: str) -> QImage:
    return glyph_pixmap(name, 48, TEXT_SECONDARY).toImage()


def test_each_command_wears_the_family_s_mark_as_the_evolver_s_menu_does(qapp):
    """The two menus sit side by side in the tray, and the Evolver's marks every
    command it offers; the status line, which cannot be clicked, carries none."""

    tray = BrokerTray()

    assert tray.status_action.icon().isNull()
    assert _drawn(tray.start_action.icon()) == _family_mark("play")
    assert _drawn(tray.pause_action.icon()) == _family_mark("pause")
    assert _drawn(tray.log_action.icon()) == _family_mark("log")
    assert _drawn(tray.quit_action.icon()) == _family_mark("power")


def test_supervisor_reads_liveness_from_the_broker_s_own_mutex(cfg_path):
    config = load_config(cfg_path)
    probed = []
    supervisor = BrokerSupervisor(
        config,
        launch=lambda argv: None,
        terminate=lambda: None,
        is_held=lambda name: probed.append(name) or True,
    )

    assert supervisor.is_running()
    assert probed == [mutex_name(MUTEX_BROKER, config.config_path)]


def _supervisor(cfg_path, *, running=False, running_from=PROJECT_DIR):
    """A supervisor over a real config, with its launch/kill seams recorded, and
    a running broker that says it runs from *running_from* (None: says nothing)."""

    calls = {"launched": [], "terminated": 0}

    def terminate():
        calls["terminated"] += 1

    config = load_config(cfg_path)
    if running and running_from is not None:
        config.broker_checkout_file.write_text(str(running_from), encoding="utf-8")
    supervisor = BrokerSupervisor(
        config,
        launch=calls["launched"].append,
        terminate=terminate,
        is_held=lambda name: running,
    )
    return supervisor, calls


def test_start_runs_the_broker_module_against_our_config(cfg_path):
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


def test_a_tray_starts_the_broker_from_its_own_checkout(cfg_path):
    """So a branch's tray runs the branch's broker: `-m` finds the package in
    the working directory first."""
    closed = MagicMock(pid=4321)
    closed.wait.return_value = 0
    with patch.object(tray_module.subprocess, "Popen", return_value=closed) as popen:
        tray_module.launch_broker(["broker"], load_config(cfg_path), logging.getLogger("test.tray"))
    popen.call_args.kwargs["stdout"].close()

    assert popen.call_args.kwargs["cwd"] == str(PROJECT_DIR)


def test_the_tray_logs_how_a_broker_it_launched_ended(cfg_path):
    crashed = MagicMock(pid=4321)
    crashed.wait.return_value = 0xC0000005

    with (
        what_is_said_on("test.tray") as heard,
        patch.object(tray_module.subprocess, "Popen", return_value=crashed) as popen,
    ):
        tray_module.launch_broker(["broker"], load_config(cfg_path), logging.getLogger("test.tray"))
        popen.call_args.kwargs["stdout"].close()
        ended = heard.first_saying("ended", timeout=5.0)

    assert "4321" in ended
    assert "0xc0000005" in ended


def test_start_leaves_a_live_broker_alone(cfg_path):
    supervisor, calls = _supervisor(cfg_path, running=True)

    supervisor.start()

    assert calls["launched"] == []


def test_start_replaces_a_broker_another_checkout_started(cfg_path, tmp_path):
    """How a branch's preview tray comes to run the branch's broker, and how the
    usual tray takes the usual broker back after it."""
    supervisor, calls = _supervisor(cfg_path, running=True, running_from=tmp_path / "elsewhere")

    supervisor.start()

    assert calls["terminated"] == 1
    assert len(calls["launched"]) == 1


def test_start_replaces_a_broker_that_never_said_where_it_runs_from(cfg_path):
    supervisor, calls = _supervisor(cfg_path, running=True, running_from=None)

    supervisor.start()

    assert calls["terminated"] == 1
    assert len(calls["launched"]) == 1


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


@pytest.fixture
def tray(qapp):

    return BrokerTray()


def test_watchdog_revives_a_dead_broker(tray, cfg_path):

    supervisor = FakeSupervisor(running=False)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.tick()

    assert supervisor.starts == 1


def test_watchdog_leaves_a_paused_broker_dead(tray, cfg_path):
    """Pause must survive the next tick, or the tray fights the user."""

    supervisor = FakeSupervisor(running=True)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.pause()
    app.tick()

    assert supervisor.stops == 1
    assert supervisor.starts == 0


def test_starting_by_hand_clears_the_pause(tray, cfg_path):

    supervisor = FakeSupervisor(running=False)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.pause()
    app.start_or_restart()
    app.tick()

    assert supervisor.starts == 1


def test_restart_from_the_menu_replaces_a_live_broker(tray, cfg_path):
    """On a running broker the menu says 'Restart Broker', and it must mean it:
    because start() is idempotent, collapsing the restart branch into start()
    turns the menu item into a silent no-op — and until this test, nothing
    noticed (audit finding broker/all/tests/013)."""

    supervisor = FakeSupervisor(running=True)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.start_or_restart()

    assert supervisor.restarts == 1
    assert supervisor.starts == 0


def test_a_failed_beat_does_not_stop_the_watchdog(tray, cfg_path):
    """The tray is the broker's only supervisor; one bad tick must not end it."""


    class ExplodingSupervisor(FakeSupervisor):
        def is_running(self):
            raise OSError("WMI hiccup")

    app = BrokerTrayApp(load_config(cfg_path), ExplodingSupervisor(), tray)

    with pytest.raises(OSError):
        app.tick()

    _guarded_tick(app, logging.getLogger("test-watchdog"))


def test_opening_the_log_creates_it_first_so_the_editor_has_something(tray, cfg_path):

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

    supervisor = FakeSupervisor(running=True)
    quit_calls = []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray,
                        quit_app=lambda: quit_calls.append(True))

    app.quit()

    assert supervisor.stops == 1
    assert not tray.isVisible()
    assert quit_calls == [True]


def test_quitting_a_preview_hands_the_broker_back_still_running(tray, cfg_path):
    """The usual tray takes the broker over again: stopping it would take the
    device away, and standing it down would stop Evolver bringing that tray
    back."""

    supervisor = FakeSupervisor(running=True)
    stood_down, handed_back, quit_calls = [], [], []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray,
                        stand_down=lambda: stood_down.append(True),
                        hand_back=lambda: handed_back.append(True),
                        quit_app=lambda: quit_calls.append(True))

    app.quit()

    assert handed_back == [True]
    assert stood_down == []
    assert supervisor.stops == 0
    assert not tray.isVisible()
    assert quit_calls == [True]


def test_making_way_for_an_update_stops_the_broker_before_the_next_tray_is_started(tray, cfg_path):
    """Nothing of this checkout may still run while the next tray's launcher updates
    it, and Evolver must go on bringing the tray back should that tray never start."""
    supervisor = FakeSupervisor(running=True)
    stood_down, started_with_the_broker_running, quit_calls = [], [], []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray,
                        stand_down=lambda: stood_down.append(True),
                        quit_app=lambda: quit_calls.append(True))

    app.make_way_for_an_update(
        start_the_next_tray=lambda: started_with_the_broker_running.append(supervisor.running))

    assert started_with_the_broker_running == [False]
    assert stood_down == []
    assert not tray.isVisible()
    assert quit_calls == [True]


class FakeUpdateWatch:
    def __init__(self):
        self.ticks = 0

    def tick(self):
        self.ticks += 1


def test_the_watchdog_looks_for_an_update_on_every_beat(tray, cfg_path):
    updates = FakeUpdateWatch()
    app = BrokerTrayApp(load_config(cfg_path), FakeSupervisor(running=True), tray, updates=updates)

    app.tick()

    assert updates.ticks == 1


def test_a_paused_broker_takes_no_update(tray, cfg_path):
    """The next tray would come up knowing nothing of the pause, and start the broker."""
    updates = FakeUpdateWatch()
    app = BrokerTrayApp(load_config(cfg_path), FakeSupervisor(running=True), tray, updates=updates)

    app.pause()
    app.tick()

    assert updates.ticks == 0


def test_a_second_tray_stands_down(cfg_path):
    """The scheduled task relaunches the tray every couple of minutes."""



    # main() installs its process-wide scaffolding before it reaches the mutex
    # check, and none of it belongs to the rest of the session: both excepthooks
    # replaced by one that logs to the 'osr2_broker.tray' logger, a rotating file
    # handler on that logger pointed inside a state directory this test is about
    # to delete, and -- on Windows -- pythonw.exe copied into the live .venv and
    # stamped. tests/test_app.py patches the same three for the broker's own
    # main().
    with patch.object(tray_module, "configure_logging",
                      return_value=logging.getLogger("test.tray")), \
         patch.object(tray_module, "install_exception_logging"), \
         patch.object(tray_module, "_name_this_process"), \
         patch.object(tray_module, "try_acquire_mutex", return_value=None) as acquire:
        assert tray_module.main(["--config", str(cfg_path)]) == 0

    acquire.assert_called_once_with(tray_module.MUTEX_TRAY)


def test_a_preview_takes_the_tray_over_and_leaves_the_everyday_interpreter_unnamed(
        cfg_path, monkeypatch):
    """Naming would write a copy of the interpreter into the everyday
    checkout's venv, which the usual tray names for itself."""
    monkeypatch.setenv(branch_session.FLAG, "1")

    with patch.object(tray_module, "configure_logging",
                      return_value=logging.getLogger("test.tray")), \
         patch.object(tray_module, "install_exception_logging"), \
         patch.object(tray_module, "_name_this_process") as named, \
         patch.object(branch_session, "take_the_tray_over", return_value=None) as took_over:
        assert tray_module.main(["--config", str(cfg_path)]) == 0

    named.assert_not_called()
    took_over.assert_called_once_with(end_the_other_trays=branch_session.end_the_other_trays)


def test_a_preview_s_tray_names_the_feature_it_demos_and_hands_the_tray_back(qapp, cfg_path, monkeypatch):
    handed_back, quits = [], []
    monkeypatch.setattr(branch_session, "hand_back",
                        lambda config, claim: handed_back.append(claim))

    tray, _, hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), 42,
        hands_back=True, shown_as=Preview(feature="the new idle alert"),
        quit_app=lambda: quits.append(True))
    tray.set_status(running=False, osr2="OSR2 off")
    tray.quit_action.trigger()

    assert tray.toolTip() == "Broker — preview of the new idle alert: stopped"
    assert handed_back == [42]
    assert quits == [True]
    assert hand_back_timer.interval() == branch_session.HAND_BACK_AFTER_MINUTES * 60_000


def test_a_preview_s_tray_wears_the_brokers_letter_in_the_preview_ink(qapp, cfg_path):
    tray, _, _hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), 42,
        hands_back=True, shown_as=Preview(feature=None), quit_app=lambda: None)

    middle_bar_of_the_b = tray.icon().pixmap(256, 256).toImage().pixelColor(128, 128)
    assert (middle_bar_of_the_b.red(), middle_bar_of_the_b.green(), middle_bar_of_the_b.blue()) == PREVIEW_INK


def test_the_usual_tray_never_hands_itself_back(qapp, cfg_path):
    _tray, _, hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), 42,
        hands_back=False, shown_as=None, quit_app=lambda: None)

    assert hand_back_timer is None


@pytest.fixture
def an_update_waiting(monkeypatch):
    """A beat of a tray start_the_tray builds reaches the machine's brokers and this
    checkout's update; these stand in for both, and the tray may take it at once."""
    happened = []
    monkeypatch.setattr(tray_module.production_update, "UP_BEFORE_AN_UPDATE_S", 0.0)
    monkeypatch.setattr(tray_module, "launch_broker", lambda argv, config, logger: None)
    monkeypatch.setattr(tray_module, "terminate_broker", lambda logger: happened.append("stopped the broker"))
    monkeypatch.setattr(tray_module.production_update, "waits_for_programs_to_close",
                        lambda checkout: checkout == PROJECT_DIR)
    monkeypatch.setattr(tray_module.production_update, "start_again_after",
                        lambda pid, launcher: happened.append(f"{launcher.name} once {pid} has ended"))
    return happened


def test_the_usual_tray_starts_again_for_an_update_waiting_on_its_checkout(qapp, cfg_path, an_update_waiting):
    _tray, tray_app, _ = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), 42,
        hands_back=False, shown_as=None, quit_app=lambda: an_update_waiting.append("quit"))

    tray_app.tick()

    assert an_update_waiting == [
        "stopped the broker", f"launch_broker_tray.vbs once {os.getpid()} has ended", "quit"]


def test_the_usual_tray_takes_no_update_while_the_osr2_is_on(qapp, cfg_path, an_update_waiting):
    config = load_config(cfg_path)
    publish_stamp(config.osr2_serial_rx_file)
    _tray, tray_app, _ = tray_module.start_the_tray(
        config, logging.getLogger("test.tray"), 42,
        hands_back=False, shown_as=None, quit_app=lambda: an_update_waiting.append("quit"))

    tray_app.tick()

    assert an_update_waiting == []


def test_a_preview_never_starts_again_for_an_update(qapp, cfg_path, an_update_waiting):
    _tray, tray_app, _ = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), 42,
        hands_back=True, shown_as=Preview(feature=None), quit_app=lambda: an_update_waiting.append("quit"))

    tray_app.tick()

    assert an_update_waiting == []


def test_hovering_the_usual_tray_names_the_app_broker(qapp, cfg_path):
    tray, _, _hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), 42,
        hands_back=False, shown_as=None, quit_app=lambda: None)

    tray.set_status(running=True, osr2="controlling OSR2")

    assert tray.toolTip() == "Broker: running (controlling OSR2)"


def _ticked(tray, cfg_path, *, mode_written: str | None, osr2_spoke: bool):
    config = load_config(cfg_path)
    if mode_written is not None:
        config.broker_mode_file.write_text(mode_written, encoding="utf-8")
    if osr2_spoke:
        publish_stamp(config.osr2_serial_rx_file)
    BrokerTrayApp(config, FakeSupervisor(running=True), tray).tick()
    return tray


def test_hovering_says_the_broker_is_controlling_an_osr2_that_is_on(tray, cfg_path):

    ticked = _ticked(tray, cfg_path, mode_written="0", osr2_spoke=True)

    assert ticked.toolTip() == "Broker: running (controlling OSR2)"


def test_a_broker_that_has_written_no_mode_yet_is_controlling_the_osr2(tray, cfg_path):

    ticked = _ticked(tray, cfg_path, mode_written=None, osr2_spoke=True)

    assert ticked.toolTip() == "Broker: running (controlling OSR2)"


@pytest.mark.parametrize("mode_written", ["0", "1"])
def test_hovering_says_the_osr2_is_off_while_it_has_not_spoken(tray, cfg_path, mode_written):

    ticked = _ticked(tray, cfg_path, mode_written=mode_written, osr2_spoke=False)

    assert ticked.toolTip() == "Broker: running (OSR2 off)"


@pytest.mark.parametrize(("stamp", "said"), [("osr2_not_found_file", "OSR2 unplugged"),
                                              ("osr2_not_answering_file", "OSR2 no answer")])
def test_hovering_names_why_the_osr2_cannot_be_heard(tray, cfg_path, stamp, said):
    publish_stamp(getattr(load_config(cfg_path), stamp))

    ticked = _ticked(tray, cfg_path, mode_written="0", osr2_spoke=False)

    assert ticked.toolTip() == f"Broker: running ({said})"


@pytest.mark.parametrize("mode_written", ["1", "﻿1\r\n"])
def test_the_menu_says_when_the_osr2_runs_its_own_auto_mode(tray, cfg_path, mode_written):

    ticked = _ticked(tray, cfg_path, mode_written=mode_written, osr2_spoke=True)

    assert ticked.status_action.text() == "Broker status: running (but OSR2 in auto mode)"


def test_running_broker_offers_a_restart_and_a_live_pause(qapp):

    tray = BrokerTray()
    tray.set_status(running=True, osr2="but OSR2 in auto mode")

    assert tray.status_action.text() == "Broker status: running (but OSR2 in auto mode)"
    assert tray.start_action.text() == "Restart Broker"
    assert _drawn(tray.start_action.icon()) == _family_mark("restart")
    assert tray.pause_action.isEnabled()
    assert tray.toolTip() == "Broker: running (but OSR2 in auto mode)"


def test_stopped_broker_offers_a_start_and_a_dead_pause(qapp):

    tray = BrokerTray()
    tray.set_status(running=False, osr2="OSR2 off")

    assert tray.status_action.text() == "Broker status: stopped"
    assert tray.start_action.text() == "Start Broker"
    assert _drawn(tray.start_action.icon()) == _family_mark("play")
    assert not tray.pause_action.isEnabled()
    assert tray.toolTip() == "Broker: stopped"


def test_a_preview_s_tray_says_so_on_hover(qapp):

    tray = BrokerTray("Broker — preview of claude/example")
    tray.set_status(running=True, osr2="OSR2 off")

    assert tray.toolTip() == "Broker — preview of claude/example: running (OSR2 off)"


def test_a_preview_tray_wears_what_its_checkout_describes(monkeypatch):
    described = Preview(feature="the new idle alert")
    monkeypatch.setattr(tray_module, "preview_of", lambda checkout: described)

    assert tray_module.shown_as(preview=True) is described


def test_the_usual_tray_wears_no_preview_wherever_it_runs_from(monkeypatch):
    monkeypatch.setattr(tray_module, "preview_of", lambda checkout: Preview(feature="unused"))

    assert tray_module.shown_as(preview=False) is None
