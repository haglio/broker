from __future__ import annotations

import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from app_support.testing import stood_down, stood_down_asking

from osr2_broker import peer_watch
from osr2_broker import tray as tray_module
from osr2_broker.config import load_config
from osr2_broker.tray import BrokerTray, BrokerTrayApp, TrayHooks
from tests.conftest import _write_config

from .test_tray import FakeSupervisor

LOG = logging.getLogger("test.peer_watch")


@pytest.fixture
def tray(qapp):
    return BrokerTray()


class TestIsEvolverUp:
    def test_a_held_mutex_is_a_running_evolver(self):
        assert peer_watch.evolver_is_up(is_held=lambda name: True) is True

    def test_a_free_mutex_is_an_evolver_that_is_gone(self):
        assert peer_watch.evolver_is_up(is_held=lambda name: False) is False

    def test_it_asks_after_the_name_evolver_actually_holds(self):
        asked: list[str] = []

        peer_watch.evolver_is_up(is_held=lambda name: asked.append(name) or True)

        assert asked == ["EvolverTrayApp_SingleInstance"]


class TestStartingEvolver:
    @pytest.fixture
    def launcher(self, tmp_path):
        path = tmp_path / "launch_evolver.vbs"
        path.write_text("' launcher", encoding="utf-8")
        return path

    def test_it_runs_the_launcher_through_the_script_host(self, launcher):
        popen = MagicMock()

        peer_watch.launch_evolver(launcher, LOG, popen=popen)

        assert popen.call_args[0][0] == ["wscript.exe", str(launcher)]

    def test_it_runs_the_launcher_from_evolvers_own_directory(self, launcher):
        popen = MagicMock()

        peer_watch.launch_evolver(launcher, LOG, popen=popen)

        assert popen.call_args.kwargs["cwd"] == str(launcher.parent)

    def test_it_never_flashes_a_console_over_whatever_is_on_screen(self, launcher):
        popen = MagicMock()

        peer_watch.launch_evolver(launcher, LOG, popen=popen)

        assert popen.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW

    def test_a_machine_with_no_evolver_on_it_starts_nothing_and_says_nothing_or_the_log_would_hear_it_every_fifteen_minutes_forever(
            self, tmp_path, caplog):
        popen = MagicMock()

        with caplog.at_level(logging.DEBUG, logger=LOG.name):
            peer_watch.launch_evolver(tmp_path / "absent.vbs", LOG, popen=popen)

        popen.assert_not_called()
        assert caplog.records == []

    def test_a_launch_says_so_in_the_log(self, launcher, caplog):
        with caplog.at_level(logging.INFO, logger=LOG.name):
            peer_watch.launch_evolver(launcher, LOG, popen=MagicMock())

        assert "Evolver was not running" in caplog.text


class TestTheTrayWatchesEvolverWhichHasNoSupervisorOfItsOwnAndWatchesBack:
    def _watch(self, cfg_path):
        return peer_watch.watch_evolver(load_config(cfg_path), LOG)

    def test_an_evolver_that_is_up_is_left_alone_nothing_here_ever_ends_one_a_kill_on_a_misread_could_not_be_undone(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=True), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        launch.assert_not_called()

    def test_an_evolver_that_is_gone_is_started(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             stood_down(False), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        launch.assert_called_once()

    def test_it_starts_the_launcher_the_config_names(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             stood_down(False), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        assert launch.call_args[0][0] == load_config(cfg_path).evolver_launcher

    def test_an_evolver_the_user_closed_is_left_closed(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             stood_down(True), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        launch.assert_not_called()

    def test_the_watch_asks_after_the_key_evolver_stands_itself_down_under(self, cfg_path):
        asked: list[str] = []

        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             stood_down_asking(side_effect=lambda key, **kw: asked.append(key) or False), \
             patch.object(peer_watch, "launch_evolver"):
            self._watch(cfg_path).tick()

        assert asked == ["evolver"]


class TestWhereTheLauncherComesFrom:
    def test_it_defaults_to_the_sibling_checkout(self, cfg_path):
        launcher = load_config(cfg_path).evolver_launcher

        assert launcher.parent.name == "evolver"

    def test_it_starts_the_launcher_that_leaves_an_evolver_already_running_alone(
            self, cfg_path):
        launcher = load_config(cfg_path).evolver_launcher

        assert launcher.name == "launch_evolver_if_not_running.vbs"

    def test_a_config_may_name_another(self, tmp_path):
        elsewhere = tmp_path / "somewhere" / "launch_evolver.vbs"
        config_path = _write_config(tmp_path, {"evolver_launcher": str(elsewhere)})

        assert load_config(config_path).evolver_launcher == elsewhere


class TestTheTrayKeepsTheWatch:
    def _app(self, cfg_path, tray, *, peer=None, stand_down=None, running=True):
        hooks = {"peer": peer, "quit_app": lambda: None}
        if stand_down is not None:
            hooks["stand_down"] = stand_down
        return BrokerTrayApp(
            load_config(cfg_path), FakeSupervisor(running=running), tray, TrayHooks(**hooks))

    def test_every_watchdog_beat_reaches_the_watch_which_throttles_itself_to_its_own_interval(self, tray, cfg_path):
        peer = MagicMock()

        self._app(cfg_path, tray, peer=peer).tick()

        peer.tick.assert_called_once()

    def test_pausing_the_broker_does_not_stop_watching_evolver_the_pause_is_about_the_osr2_not_the_app_next_door(self, tray, cfg_path):
        peer = MagicMock()
        app = self._app(cfg_path, tray, peer=peer)

        app.pause()
        peer.tick.reset_mock()
        app.tick()

        peer.tick.assert_called_once()

    def test_a_tray_with_no_peer_still_beats(self, tray, cfg_path):
        self._app(cfg_path, tray).tick()

    def test_quitting_stands_the_broker_down_every_other_death_of_the_tray_leaves_no_mark_and_evolver_undoes_it(self, tray, cfg_path):
        stood_down: list[str] = []

        app = self._app(cfg_path, tray, stand_down=lambda: stood_down.append("marked"))
        app.quit()

        assert stood_down == ["marked"]

    def test_quitting_marks_the_stand_down_before_the_broker_goes_so_a_tray_killed_mid_quit_still_leaves_it_for_evolver(self, tray, cfg_path):
        order: list[str] = []
        supervisor = FakeSupervisor(running=True)
        supervisor.stop = lambda: order.append("stopped")

        app = BrokerTrayApp(load_config(cfg_path), supervisor, tray, TrayHooks(stand_down=lambda: order.append("marked"), quit_app=lambda: None))
        app.quit()

        assert order == ["marked", "stopped"]

    def test_the_default_stand_down_is_the_brokers_own_key_spelled_here_as_evolver_reads_it_since_the_two_share_no_code(
            self, tray, cfg_path, stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker):
        wrote, _ = stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker

        self._app(cfg_path, tray).quit()

        assert wrote.call_args[0][0] == "broker"


class TestStartingTheTray:
    def test_a_relaunch_over_a_live_tray_leaves_the_stand_down_alone_the_scheduled_task_relaunches_every_two_minutes(
            self, cfg_path, stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker,
            the_trays_main_kept_from_the_excepthooks_the_log_file_and_a_copy_of_pythonw_into_the_live_venv):
        with patch.object(tray_module, "try_acquire_mutex", return_value=None):
            assert tray_module.main(["--config", str(cfg_path)]) == 0

        _, cleared = stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker
        cleared.assert_not_called()

    def test_the_clear_names_the_broker(self, stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker):
        peer_watch.clear_broker_stand_down()

        _, cleared = stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker
        assert cleared.call_args[0][0] == "broker"
