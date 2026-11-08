from __future__ import annotations

import logging
import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from app_support.file_channel import publish_stamp
from app_support.win32 import mutex_name
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QImage
from shared_ui.colors import BG_TERTIARY, BLUE, TEXT_SECONDARY
from shared_ui.icons import icon_pixmap
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

from osr2_broker import branch_session
from osr2_broker import tray as tray_module
from osr2_broker.config import PROJECT_DIR, load_config
from osr2_broker.process_names import BROKER_ROLE, NAMER
from osr2_broker.single_instance import MUTEX_BROKER
from osr2_broker.tray import BrokerSupervisor, BrokerTray, BrokerTrayApp, TrayHooks, _guarded_tick
from tests.heard import what_is_said_on


def _the_trays_own_menu_drawn_an_empty_one_has_no_width(tray):
    menu = tray.contextMenu()
    menu.resize(menu.sizeHint())
    return menu, menu.grab().toImage()


def _inside_the_row_clear_of_its_border_and_of_its_text_in_any_font(row):
    return row.right() - 2, row.center().y()


def test_a_tray_menu_has_no_window_to_take_the_familys_rules_from_so_it_sets_them_itself_and_paints_dark(qapp):
    tray = BrokerTray()
    menu, image = _the_trays_own_menu_drawn_an_empty_one_has_no_width(tray)

    row = menu.actionGeometry(tray.start_action)
    pixel = image.pixelColor(*_inside_the_row_clear_of_its_border_and_of_its_text_in_any_font(row))
    assert pixel.name() == BG_TERTIARY.name()


def _brightest_text_pixel(image, rect):
    return max(
        max(image.pixelColor(x, y).getRgb()[:3])
        for y in range(rect.top(), rect.bottomLeft().y() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )


def test_the_status_line_reads_as_a_label_not_a_command(qapp):
    tray = BrokerTray()
    menu, image = _the_trays_own_menu_drawn_an_empty_one_has_no_width(tray)

    status = _brightest_text_pixel(image, menu.actionGeometry(tray.status_action))
    command = _brightest_text_pixel(image, menu.actionGeometry(tray.start_action))
    assert status < command


def test_the_item_under_the_cursor_lights_up_in_the_familys_blue_a_stylesheet_takes_qts_own_highlight_away(qapp):
    tray = BrokerTray()
    tray.contextMenu().setActiveAction(tray.start_action)
    menu, image = _the_trays_own_menu_drawn_an_empty_one_has_no_width(tray)

    row = menu.actionGeometry(tray.start_action)
    fill = image.pixelColor(*_inside_the_row_clear_of_its_border_and_of_its_text_in_any_font(row))
    assert fill.name() == BLUE.name()


def test_tray_menu_offers_the_broker_controls_laid_out_as_the_evolver_s_are(qapp):
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


def _family_icon(name: str) -> QImage:
    return icon_pixmap(name, 48, TEXT_SECONDARY).toImage()


def test_each_command_wears_the_family_s_icon_as_the_evolver_s_menu_does(qapp):
    tray = BrokerTray()

    assert tray.status_action.icon().isNull()
    assert _drawn(tray.start_action.icon()) == _family_icon("play")
    assert _drawn(tray.pause_action.icon()) == _family_icon("pause")
    assert _drawn(tray.log_action.icon()) == _family_icon("log")
    assert _drawn(tray.quit_action.icon()) == _family_icon("power")


def test_supervisor_reads_liveness_from_the_brokers_own_per_config_mutex_so_a_broker_on_another_config_runs_beside_it_which_answers_at_once_never_a_process_scan_that_could_take_a_command_line_naming_it_for_it(cfg_path):
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

    the_copy_or_the_bare_interpreter_when_the_copy_cannot_be_made = NAMER.named_exe(
        sys.executable, BROKER_ROLE)
    assert calls["launched"] == [
        [the_copy_or_the_bare_interpreter_when_the_copy_cannot_be_made, "-m", "osr2_broker.app",
         "--config", str(cfg_path)],
    ]


def test_a_tray_starts_the_broker_from_its_own_checkout_where_python_m_finds_the_package_first_so_a_branchs_tray_runs_the_branchs_broker(cfg_path):
    closed = MagicMock(pid=4321)
    closed.wait.return_value = 0
    with patch.object(tray_module.subprocess, "Popen", return_value=closed) as popen:
        tray_module.LaunchedBrokers(load_config(cfg_path), logging.getLogger("test.tray")).launch(["broker"])
    popen.call_args.kwargs["stdout"].close()

    assert popen.call_args.kwargs["cwd"] == str(PROJECT_DIR)


def test_the_tray_logs_how_a_broker_it_launched_ended(cfg_path):
    crashed = MagicMock(pid=4321)
    crashed.wait.return_value = 0xC0000005

    with (
        what_is_said_on("test.tray") as heard,
        patch.object(tray_module.subprocess, "Popen", return_value=crashed) as popen,
    ):
        tray_module.LaunchedBrokers(load_config(cfg_path), logging.getLogger("test.tray")).launch(["broker"])
        popen.call_args.kwargs["stdout"].close()
        ended = heard.first_saying("ended", timeout=5.0)

    assert "4321" in ended
    assert "0xc0000005" in ended


def test_start_leaves_a_live_broker_alone(cfg_path):
    supervisor, calls = _supervisor(cfg_path, running=True)

    supervisor.start()

    assert calls["launched"] == []


def test_start_replaces_a_broker_another_checkout_started_so_a_previews_tray_runs_its_branchs_broker_and_the_production_tray_takes_it_back(cfg_path, tmp_path):
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
    def __init__(self, running=False):
        self.running = running
        self.starts = 0
        self.stops = 0
        self.restarts = 0

    def is_running(self):
        return self.running

    def start(self):
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
    supervisor = FakeSupervisor(running=True)
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray)

    app.start_or_restart()

    assert supervisor.restarts == 1
    assert supervisor.starts == 0


def test_a_failed_beat_does_not_stop_the_watchdog_the_tray_is_the_brokers_only_supervisor(tray, cfg_path):
    class ExplodingSupervisor(FakeSupervisor):
        def is_running(self):
            raise OSError("WMI hiccup")

    app = BrokerTrayApp(load_config(cfg_path), ExplodingSupervisor(), tray)

    with pytest.raises(OSError, match="WMI hiccup"):
        app.tick()

    _guarded_tick(app, logging.getLogger("test-watchdog"))


def test_opening_the_log_creates_it_first_so_the_editor_has_something(tray, cfg_path):
    config = load_config(cfg_path)
    opened = []
    app = BrokerTrayApp(
        config, FakeSupervisor(), tray, TrayHooks(open_file=opened.append))

    app.open_log()

    log_path = config.log_file("broker")
    assert log_path.exists()
    assert opened == [log_path]


def test_quitting_takes_the_broker_down_with_the_tray_nothing_else_would_supervise_it(tray, cfg_path):
    supervisor = FakeSupervisor(running=True)
    quit_calls = []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray, TrayHooks(quit_app=lambda: quit_calls.append(True)))

    app.quit()

    assert supervisor.stops == 1
    assert not tray.isVisible()
    assert quit_calls == [True]


def test_quitting_a_preview_hands_the_broker_back_running_stopping_it_would_take_the_device_away_and_a_stand_down_would_keep_evolver_from_bringing_the_production_tray_back(tray, cfg_path):
    supervisor = FakeSupervisor(running=True)
    stood_down, handed_back, quit_calls = [], [], []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray, TrayHooks(stand_down=lambda: stood_down.append(True),
                        hand_back=lambda: handed_back.append(True),
                        quit_app=lambda: quit_calls.append(True)))

    app.quit()

    assert handed_back == [True]
    assert stood_down == []
    assert supervisor.stops == 0
    assert not tray.isVisible()
    assert quit_calls == [True]


def test_making_way_for_an_update_stops_the_broker_first_nothing_of_this_checkout_may_run_while_it_updates_and_stands_nothing_down_so_evolver_still_brings_a_tray_back(tray, cfg_path):
    supervisor = FakeSupervisor(running=True)
    stood_down, started_with_the_broker_running, quit_calls = [], [], []
    app = BrokerTrayApp(load_config(cfg_path), supervisor, tray, TrayHooks(stand_down=lambda: stood_down.append(True),
                        quit_app=lambda: quit_calls.append(True)))

    app.make_way_for_an_update(
        start_the_next_tray=lambda: started_with_the_broker_running.append(supervisor.running))

    assert started_with_the_broker_running == [False]
    assert stood_down == []
    assert not tray.isVisible()
    assert quit_calls == [True]


def test_a_stop_another_app_asks_for_ends_the_broker_and_the_tray_on_the_next_beat(tray, cfg_path):
    config = load_config(cfg_path)
    supervisor = FakeSupervisor(running=True)
    stood_down, quit_calls = [], []
    app = BrokerTrayApp(config, supervisor, tray, TrayHooks(stand_down=lambda: stood_down.append(True),
                        quit_app=lambda: quit_calls.append(True)))
    publish_stamp(config.stop_request_file)

    app.tick()

    assert (supervisor.stops, supervisor.starts) == (1, 0)
    assert stood_down == []
    assert not tray.isVisible()
    assert quit_calls == [True]
    assert not config.stop_request_file.exists()


def test_a_stop_asked_for_before_the_tray_started_is_dropped_rather_than_answered(tray, cfg_path):
    config = load_config(cfg_path)
    publish_stamp(config.stop_request_file)
    supervisor = FakeSupervisor(running=False)
    quit_calls = []
    app = BrokerTrayApp(config, supervisor, tray, TrayHooks(quit_app=lambda: quit_calls.append(True)))

    app.tick()

    assert supervisor.starts == 1
    assert quit_calls == []
    assert not config.stop_request_file.exists()


class FakeUpdateWatch:
    def __init__(self):
        self.ticks = 0

    def tick(self):
        self.ticks += 1


def test_the_watchdog_looks_for_an_update_on_every_beat(tray, cfg_path):
    updates = FakeUpdateWatch()
    app = BrokerTrayApp(load_config(cfg_path), FakeSupervisor(running=True), tray, TrayHooks(updates=updates))

    app.tick()

    assert updates.ticks == 1


def test_a_paused_broker_takes_no_update_the_next_tray_would_know_nothing_of_the_pause_and_start_the_broker(tray, cfg_path):
    updates = FakeUpdateWatch()
    app = BrokerTrayApp(load_config(cfg_path), FakeSupervisor(running=True), tray, TrayHooks(updates=updates))

    app.pause()
    app.tick()

    assert updates.ticks == 0


def test_a_second_tray_stands_down(
        cfg_path,
        the_trays_main_kept_from_the_excepthooks_the_log_file_and_a_copy_of_pythonw_into_the_live_venv):
    with patch.object(tray_module, "try_acquire_mutex", return_value=None) as acquire:
        assert tray_module.main(["--config", str(cfg_path)]) == 0

    acquire.assert_called_once_with(tray_module.MUTEX_TRAY)


def test_a_preview_takes_the_tray_over_and_leaves_the_production_interpreter_unnamed_naming_would_write_a_copy_into_the_production_venv_which_the_production_tray_names_for_itself(
        cfg_path, monkeypatch,
        the_trays_main_kept_from_the_excepthooks_the_log_file_and_a_copy_of_pythonw_into_the_live_venv):
    monkeypatch.setenv(branch_session.FLAG, "1")
    named = []
    monkeypatch.setattr(tray_module, "_name_this_process", lambda: named.append(True))

    with patch.object(branch_session, "take_the_tray_over", return_value=None) as took_over:
        assert tray_module.main(["--config", str(cfg_path)]) == 0

    assert named == []
    took_over.assert_called_once_with(end_the_other_trays=branch_session.end_the_other_trays)


def test_a_preview_s_tray_names_the_feature_it_demos_and_hands_the_tray_back(qapp, cfg_path, monkeypatch):
    handed_back, quits = [], []
    monkeypatch.setattr(branch_session, "hand_back",
                        lambda config, claim: handed_back.append(claim))

    tray, _, hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), preview_claim=42,
        shown_as=Preview(feature="the new idle warning"),
        quit_app=lambda: quits.append(True))
    tray.set_status(running=False, osr2="OSR2 off")
    tray.quit_action.trigger()

    assert tray.toolTip() == "Broker — preview of the new idle warning: stopped"
    assert handed_back == [42]
    assert quits == [True]
    assert hand_back_timer.interval() == branch_session.HAND_BACK_AFTER_MINUTES * 60_000


def test_a_preview_s_tray_wears_the_brokers_letter_in_the_preview_ink(qapp, cfg_path):
    tray, _, _hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), preview_claim=42,
        shown_as=Preview(feature=None), quit_app=lambda: None)

    middle_bar_of_the_b = tray.icon().pixmap(256, 256).toImage().pixelColor(128, 128)
    assert (middle_bar_of_the_b.red(), middle_bar_of_the_b.green(), middle_bar_of_the_b.blue()) == PREVIEW_INK


def test_the_production_tray_never_hands_itself_back(qapp, cfg_path):
    _tray, _, hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), preview_claim=None,
        shown_as=None, quit_app=lambda: None)

    assert hand_back_timer is None


@pytest.fixture
def an_update_waiting(monkeypatch):
    happened = []
    monkeypatch.setattr(tray_module.production_update, "UP_BEFORE_AN_UPDATE_S", 0.0)

    class _Brokers:
        def __init__(self, _config, _logger):
            pass

        def launch(self, _argv):
            pass

        def terminate(self):
            happened.append("stopped the broker")

    monkeypatch.setattr(tray_module, "LaunchedBrokers", _Brokers)
    monkeypatch.setattr(tray_module.production_update, "waits_for_programs_to_close",
                        lambda checkout: checkout == PROJECT_DIR)
    monkeypatch.setattr(tray_module.production_update, "start_again_after",
                        lambda pid, launcher: happened.append(f"{launcher.name} once {pid} has ended"))
    return happened


def test_the_production_tray_starts_again_for_an_update_waiting_on_its_checkout(qapp, cfg_path, an_update_waiting):
    _tray, tray_app, _ = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), preview_claim=None,
        shown_as=None, quit_app=lambda: an_update_waiting.append("quit"))

    tray_app.tick()

    assert an_update_waiting == [
        "stopped the broker", f"launch_broker_tray.vbs once {os.getpid()} has ended", "quit"]


def test_the_production_tray_takes_no_update_while_the_osr2_is_on(qapp, cfg_path, an_update_waiting):
    config = load_config(cfg_path)
    publish_stamp(config.osr2_serial_rx_file)
    _tray, tray_app, _ = tray_module.start_the_tray(
        config, logging.getLogger("test.tray"), preview_claim=None,
        shown_as=None, quit_app=lambda: an_update_waiting.append("quit"))

    tray_app.tick()

    assert an_update_waiting == []


def test_a_preview_never_starts_again_for_an_update(qapp, cfg_path, an_update_waiting):
    _tray, tray_app, _ = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), preview_claim=42,
        shown_as=Preview(feature=None), quit_app=lambda: an_update_waiting.append("quit"))

    tray_app.tick()

    assert an_update_waiting == []


def test_hovering_the_production_tray_names_the_app_broker(qapp, cfg_path):
    tray, _, _hand_back_timer = tray_module.start_the_tray(
        load_config(cfg_path), logging.getLogger("test.tray"), preview_claim=None,
        shown_as=None, quit_app=lambda: None)

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
    assert _drawn(tray.start_action.icon()) == _family_icon("restart")
    assert tray.pause_action.isEnabled()
    assert tray.toolTip() == "Broker: running (but OSR2 in auto mode)"


def test_stopped_broker_offers_a_start_and_a_dead_pause(qapp):
    tray = BrokerTray()
    tray.set_status(running=False, osr2="OSR2 off")

    assert tray.status_action.text() == "Broker status: stopped"
    assert tray.start_action.text() == "Start Broker"
    assert _drawn(tray.start_action.icon()) == _family_icon("play")
    assert not tray.pause_action.isEnabled()
    assert tray.toolTip() == "Broker: stopped"


def test_a_preview_s_tray_says_so_on_hover(qapp):
    tray = BrokerTray("Broker — preview of claude/example")
    tray.set_status(running=True, osr2="OSR2 off")

    assert tray.toolTip() == "Broker — preview of claude/example: running (OSR2 off)"


def test_a_preview_tray_wears_what_its_checkout_describes(monkeypatch):
    described = Preview(feature="the new idle warning")
    monkeypatch.setattr(tray_module, "preview_of", lambda checkout: described)

    assert tray_module.shown_as(preview=True) is described


def test_the_production_tray_wears_no_preview_wherever_it_runs_from(monkeypatch):
    monkeypatch.setattr(tray_module, "preview_of", lambda checkout: Preview(feature="unused"))

    assert tray_module.shown_as(preview=False) is None


class _ABrokerThatEnds:
    pid = 1

    def wait(self) -> int:
        return 0


def test_the_broker_is_started_detached_with_no_console_of_its_own(cfg_path):
    asked = {}

    def popen(_argv, **kwargs):
        asked.update(kwargs)
        kwargs["stdout"].close()
        return _ABrokerThatEnds()

    tray_module.LaunchedBrokers(
        load_config(cfg_path), logging.getLogger("test.tray"), popen=popen).launch(["broker"])

    assert asked["creationflags"] == (
        tray_module.subprocess.CREATE_NO_WINDOW | tray_module.subprocess.DETACHED_PROCESS)


class _ABrokerTheTrayEnds:
    pid = 4321

    def __init__(self):
        self.ended = threading.Event()

    def wait(self) -> int:
        self.ended.wait(timeout=5.0)
        return 0xFFFFFFFF


def _said_ending(caplog, *, timeout: float) -> logging.LogRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for record in caplog.records:
            if "ended" in record.getMessage():
                return record
        time.sleep(0.01)
    raise AssertionError("the tray never said how the broker ended")


def _launched(broker):
    def popen(_argv, **kwargs):
        kwargs["stdout"].close()
        return broker
    return popen


def test_a_broker_the_tray_ended_itself_is_no_warning(cfg_path, caplog):
    broker = _ABrokerTheTrayEnds()
    brokers = tray_module.LaunchedBrokers(
        load_config(cfg_path), logging.getLogger("test.tray"),
        popen=_launched(broker), end_them=broker.ended.set)

    with caplog.at_level(logging.INFO, logger="test.tray"):
        brokers.launch(["broker"])
        brokers.terminate()
        ended = _said_ending(caplog, timeout=5.0)

    assert ended.levelno == logging.INFO
    assert "4321" in ended.getMessage()


def test_a_tray_started_over_a_broker_it_did_not_launch_can_still_stop_it_a_restarted_tray_holds_no_handle_for_the_one_it_inherited(cfg_path):
    ended = []
    brokers = tray_module.LaunchedBrokers(
        load_config(cfg_path), logging.getLogger("test.tray"), end_them=lambda: ended.append(True))

    brokers.terminate()

    assert ended == [True]
