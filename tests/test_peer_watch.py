"""The broker's half of the pair: what it checks, what it starts, and when it doesn't.

The policy — the throttle, the stand-down, the guard around a failing launcher —
is app_support's and is tested there. What is tested here is the part only the
broker can get wrong: which mutex answers "is Evolver up", which file is run to
start one, and that the watchdog beat reaches the watch without the broker's own
pause silencing it.
"""
from __future__ import annotations

import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from osr2_broker import peer_watch

from .test_tray import FakeSupervisor

LOG = logging.getLogger("test.peer_watch")


@pytest.fixture(scope="module")
def qapp():
    """Held for the module, not made and dropped per test.

    A QApplication nothing refers to is collected the moment it is built, and the
    next QSystemTrayIcon then faults the interpreter rather than raising.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tray(qapp):
    from osr2_broker.tray import BrokerTray

    return BrokerTray()


class TestIsEvolverUp:
    def test_a_held_mutex_is_a_running_evolver(self):
        assert peer_watch.evolver_is_up(is_held=lambda name: True) is True

    def test_a_free_mutex_is_an_evolver_that_is_gone(self):
        assert peer_watch.evolver_is_up(is_held=lambda name: False) is False

    def test_it_asks_after_the_name_evolver_actually_holds(self):
        """Unqualified, so it resolves in the logon session's own namespace —
        which is the only place either app runs."""
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

    def test_a_machine_with_no_evolver_on_it_starts_nothing(self, tmp_path):
        popen = MagicMock()

        peer_watch.launch_evolver(tmp_path / "absent.vbs", LOG, popen=popen)

        popen.assert_not_called()

    def test_a_launch_says_so_in_the_log(self, launcher, caplog):
        with caplog.at_level(logging.INFO, logger=LOG.name):
            peer_watch.launch_evolver(launcher, LOG, popen=MagicMock())

        assert "Evolver was not running" in caplog.text


class TestTheWatch:
    def _watch(self, cfg_path):
        from osr2_broker.config import load_config

        return peer_watch.watch_evolver(load_config(cfg_path), LOG)

    def test_an_evolver_that_is_up_is_left_alone(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=True), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        launch.assert_not_called()

    def test_an_evolver_that_is_gone_is_started(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             patch("app_support.peer_watch.is_stood_down", return_value=False), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        launch.assert_called_once()

    def test_it_starts_the_launcher_the_config_names(self, cfg_path):
        from osr2_broker.config import load_config

        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             patch("app_support.peer_watch.is_stood_down", return_value=False), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        assert launch.call_args[0][0] == load_config(cfg_path).evolver_launcher

    def test_an_evolver_the_user_closed_is_left_closed(self, cfg_path):
        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             patch("app_support.peer_watch.is_stood_down", return_value=True), \
             patch.object(peer_watch, "launch_evolver") as launch:
            self._watch(cfg_path).tick()

        launch.assert_not_called()

    def test_the_watch_asks_after_the_key_evolver_stands_itself_down_under(self, cfg_path):
        asked: list[str] = []

        with patch.object(peer_watch, "evolver_is_up", return_value=False), \
             patch("app_support.peer_watch.is_stood_down",
                   side_effect=lambda key, **kw: asked.append(key) or False), \
             patch.object(peer_watch, "launch_evolver"):
            self._watch(cfg_path).tick()

        assert asked == ["evolver"]


class TestWhereTheLauncherComesFrom:
    def test_it_defaults_to_the_sibling_checkout(self, cfg_path):
        from osr2_broker.config import load_config

        launcher = load_config(cfg_path).evolver_launcher

        assert launcher.name == "launch_evolver.vbs"
        assert launcher.parent.name == "evolver"

    def test_a_config_may_name_another(self, tmp_path):
        from osr2_broker.config import load_config
        from tests.conftest import _write_config

        elsewhere = tmp_path / "somewhere" / "launch_evolver.vbs"
        config_path = _write_config(tmp_path, {"evolver_launcher": str(elsewhere)})

        assert load_config(config_path).evolver_launcher == elsewhere


class TestTheTrayKeepsTheWatch:
    def _app(self, cfg_path, tray, *, peer=None, stand_down=None, running=True):
        from osr2_broker.config import load_config
        from osr2_broker.tray import BrokerTrayApp

        kwargs = {"peer": peer}
        if stand_down is not None:
            kwargs["stand_down"] = stand_down
        return BrokerTrayApp(
            load_config(cfg_path), FakeSupervisor(running=running), tray, **kwargs)

    def test_the_watchdog_beat_reaches_the_watch(self, tray, cfg_path):
        peer = MagicMock()

        self._app(cfg_path, tray, peer=peer).tick()

        peer.tick.assert_called_once()

    def test_pausing_the_broker_does_not_stop_watching_evolver(self, tray, cfg_path):
        """The pause is about the OSR2, and says nothing about the app next door."""
        peer = MagicMock()
        app = self._app(cfg_path, tray, peer=peer)

        app.pause()
        peer.tick.reset_mock()
        app.tick()

        peer.tick.assert_called_once()

    def test_a_tray_with_no_peer_still_beats(self, tray, cfg_path):
        """Every existing caller builds one this way; it must stay a no-op."""
        self._app(cfg_path, tray).tick()

    def test_quitting_stands_the_broker_down(self, tray, cfg_path):
        stood_down: list[str] = []

        app = self._app(cfg_path, tray, stand_down=lambda: stood_down.append("marked"))
        app.quit(lambda: None)

        assert stood_down == ["marked"]

    def test_quitting_stands_down_before_the_broker_goes(self, tray, cfg_path):
        """Written first, so a tray killed mid-quit still leaves the mark rather
        than a broker that is down with nothing recording that it was meant to be."""
        order: list[str] = []
        supervisor = FakeSupervisor(running=True)
        supervisor.stop = lambda: order.append("stopped")

        from osr2_broker.config import load_config
        from osr2_broker.tray import BrokerTrayApp

        app = BrokerTrayApp(load_config(cfg_path), supervisor, tray,
                            stand_down=lambda: order.append("marked"))
        app.quit(lambda: None)

        assert order == ["marked", "stopped"]

    def test_the_default_stand_down_is_the_brokers_own(self, tray, cfg_path,
                                                       stand_down_marker):
        wrote, _ = stand_down_marker

        self._app(cfg_path, tray).quit(lambda: None)

        assert wrote.call_args[0][0] == "broker"


class TestStartingTheTray:
    def test_a_relaunch_over_a_live_tray_leaves_the_stand_down_alone(
            self, cfg_path, stand_down_marker):
        """The scheduled task relaunches this every couple of minutes, and each
        relaunch exits at the mutex. If those cleared the marker, quitting the
        tray would stand the broker down for two minutes and no longer."""
        from app_support import logging_utils

        from osr2_broker import tray as tray_module

        with patch.object(logging_utils, "configure_logging", return_value=LOG),              patch.object(logging_utils, "install_exception_logging"),              patch.object(tray_module, "_name_this_process"),              patch.object(tray_module, "try_acquire_mutex", return_value=None):
            assert tray_module.main(["--config", str(cfg_path)]) == 0

        _, cleared = stand_down_marker
        cleared.assert_not_called()

    def test_the_clear_names_the_broker(self, stand_down_marker):
        peer_watch.clear_broker_stand_down()

        _, cleared = stand_down_marker
        assert cleared.call_args[0][0] == "broker"
