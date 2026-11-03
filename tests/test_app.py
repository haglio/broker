from __future__ import annotations

import importlib
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time as _time
import time as real_time
import types
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import pytest
from app_support.osr2_device import SILENT_ONCE_OFF_S

import osr2_broker.monitor as monitor_mod
from osr2_broker import idle_warning
from osr2_broker.config import PROJECT_DIR, load_config
from tests.heard import what_is_said_on


class FakeSocket:
    def sendto(self, _data, _addr):
        return None

    def close(self):
        return None


def make_fake_serial(open_ports: list[str], fail_once_on: tuple[str, type[Exception]] | None = None):
    class FakeSerial:
        def __init__(self, port, _baud, timeout=0.02):
            open_ports.append(port)
            if fail_once_on is not None:
                failing_port, error = fail_once_on
                if port == failing_port and open_ports.count(port) == 1:
                    raise error("Access is denied")
            self.port = port
            self.timeout = timeout
            self.in_waiting = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            return b""

        def write(self, _data):
            return None

    return FakeSerial


@pytest.fixture
def broker_app_module():
    fake_serial = types.SimpleNamespace(
        Serial=None,
        SerialException=type("FakeSerialException", (Exception,), {}),
    )
    borrowed_from = sys.modules.get("serial")
    sys.modules["serial"] = fake_serial
    try:
        return importlib.reload(importlib.import_module("osr2_broker.app"))
    finally:
        if borrowed_from is None:
            del sys.modules["serial"]
        else:
            sys.modules["serial"] = borrowed_from


def test_the_module_fixture_puts_back_only_the_name_it_borrowed(broker_app_module):
    for name in ("app_support.cli", "app_support.logging_utils", "app_support.threading_utils"):
        assert name in sys.modules, f"the fixture evicted {name} from sys.modules"
        package, _, attribute = name.rpartition(".")
        assert getattr(sys.modules[package], attribute) is sys.modules[name], (
            f"{package} and sys.modules disagree about which {attribute} is the real one"
        )


def _start_monitor_with_fake_guard(broker_app_module, config, *, auto_active=False):
    captured: dict = {}

    class FakeShutdownGuard:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return None

    with patch.object(broker_app_module, "ShutdownGuard", FakeShutdownGuard), \
         patch.object(broker_app_module, "start_daemon_thread"):
        broker_app_module._start_monitor(
            config, types.SimpleNamespace(is_active=auto_active),
            logging.getLogger("test.broker"),
        )
    return captured


def test_shutdown_is_blocked_while_the_device_is_on(broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    config.osr2_serial_rx_file.write_text(str(_time.time()), encoding="utf-8")

    captured = _start_monitor_with_fake_guard(broker_app_module, config)

    assert captured["should_block_fn"]() is True


def test_shutdown_is_allowed_once_the_device_has_been_silent_for_the_shared_window(
        broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    stale = _time.time() - (SILENT_ONCE_OFF_S + 0.5)
    config.osr2_serial_rx_file.write_text(str(stale), encoding="utf-8")

    captured = _start_monitor_with_fake_guard(broker_app_module, config)

    assert captured["should_block_fn"]() is False


def test_shutdown_is_allowed_when_the_device_has_never_reported(broker_app_module, cfg_path):
    config = load_config(str(cfg_path))

    captured = _start_monitor_with_fake_guard(broker_app_module, config)

    assert captured["should_block_fn"]() is False


def _an_idle_spell_already_due(config):
    now = _time.time()
    monitor_mod.save_idle_state(
        config.osr2_idle_state_file,
        idle_since=now - config.idle_minutes * 60.0 - 1.0, warned=False, saved_at=now,
    )
    config.osr2_serial_rx_file.write_text(str(now), encoding="utf-8")


def test_a_restarted_broker_resumes_the_idle_countdown_from_disk(broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    _an_idle_spell_already_due(config)

    warned = threading.Event()

    def closed(_config):
        warned.set()
        return subprocess.CompletedProcess([], 0, "", "")

    with patch.object(idle_warning, "show_until_closed", side_effect=closed):
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()
        assert warned.wait(timeout=5.0), "the idle warning never reached the warning"

    persisted = json.loads(config.osr2_idle_state_file.read_text(encoding="utf-8"))
    assert persisted["warned"] is True


def test_a_broker_started_long_after_the_last_counts_15_minutes_from_its_own_start(
        broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    now = _time.time()
    monitor_mod.save_idle_state(config.osr2_idle_state_file, idle_since=now - 7200.0,
                                warned=True, saved_at=now - 3600.0)
    config.osr2_serial_rx_file.write_text(str(now), encoding="utf-8")

    with patch.object(idle_warning, "show_until_closed") as shown:
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()

    shown.assert_not_called()
    persisted = json.loads(config.osr2_idle_state_file.read_text(encoding="utf-8"))
    assert persisted["warned"] is False
    assert persisted["idle_since"] >= now


def test_the_broker_logs_how_an_idle_warning_ended(broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    _an_idle_spell_already_due(config)
    crashed = subprocess.CompletedProcess(
        [], 0xC0000005, "", "Windows fatal exception: access violation\n")

    with what_is_said_on("test.broker") as heard, \
         patch.object(idle_warning, "show_until_closed", return_value=crashed):
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()
        ended = heard.first_saying("Idle warning", timeout=5.0)

    assert "0xc0000005" in ended
    assert "Windows fatal exception: access violation" in ended


def test_the_broker_logs_when_it_starts_and_stops_hearing_the_osr2(broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    config.osr2_serial_rx_file.write_text(str(_time.time()), encoding="utf-8")

    with what_is_said_on("test.broker") as heard:
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()
        heard.first_saying("counted as switched on", timeout=1.0)
        config.osr2_serial_rx_file.write_text(
            str(_time.time() - SILENT_ONCE_OFF_S - 1.0), encoding="utf-8")
        captured["poll_fn"]()
        heard.first_saying("counted as switched off", timeout=1.0)


def test_no_idle_warning_before_the_threshold_has_elapsed(broker_app_module, cfg_path):
    config = load_config(str(cfg_path))
    now = _time.time()
    monitor_mod.save_idle_state(
        config.osr2_idle_state_file, idle_since=now - 300.0, warned=False, saved_at=now,
    )
    config.osr2_serial_rx_file.write_text(str(now), encoding="utf-8")

    warned = []
    with patch.object(idle_warning, "show_until_closed",
                      side_effect=lambda *a, **kw: warned.append(True)):
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()

    assert warned == []
    persisted = json.loads(config.osr2_idle_state_file.read_text(encoding="utf-8"))
    assert persisted["warned"] is False


def test_the_broker_process_never_loads_qt_widgets():
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys, osr2_broker.app; print('PyQt6.QtWidgets' in sys.modules)"],
        cwd=PROJECT_DIR, env=environment, capture_output=True, text=True, check=True,
    )
    assert done.stdout.strip() == "False"


@contextmanager
def _main_running(broker_app_module, *, fake_serial, sleep, mfp_config_error=None,
                  osr2_adapters=("COM4",)):
    patches = [
        patch.object(broker_app_module, "OSR2_SLOT", 0),
        patch.object(broker_app_module, "configure_logging",
                     return_value=logging.getLogger("test.broker")),
        patch.object(broker_app_module, "install_exception_logging"),
        patch.object(broker_app_module, "try_acquire_mutex", return_value=42),
        patch.object(broker_app_module, "resolve_virtual_port",
                     side_effect=lambda _config, port, _logger: port),
        patch.object(broker_app_module, "ensure_mfp_serial_port",
                     side_effect=mfp_config_error),
        patch.object(broker_app_module.serial, "Serial", side_effect=fake_serial),
        patch.object(broker_app_module, "_start_monitor"),
        patch("osr2_broker.osr2_port.osr2_adapters", side_effect=osr2_adapters)
        if callable(osr2_adapters)
        else patch("osr2_broker.osr2_port.osr2_adapters", return_value=list(osr2_adapters)),
        patch.object(broker_app_module.time, "sleep", side_effect=sleep),
        patch.object(broker_app_module, "SERIAL_RETRY_DELAY_SECONDS", 0.0),
    ]
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        mock_socket_mod = stack.enter_context(patch.object(broker_app_module, "socket"))
        mock_socket_mod.socket.return_value = FakeSocket()
        mock_socket_mod.AF_INET = 2
        mock_socket_mod.SOCK_DGRAM = 2
        yield


class TestMainReconnect:
    def test_retries_after_retryable_serial_open_failure(self, broker_app_module, cfg_path,
                                                         caplog):
        caplog.set_level(logging.INFO, logger="test.broker")
        open_ports: list[str] = []
        FakeSerial = make_fake_serial(
            open_ports, fail_once_on=("COM4", broker_app_module.serial.SerialException),
        )

        sleep_calls = {"count": 0}

        def fake_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 4:
                raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=fake_sleep,):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        assert open_ports.count("COM4") >= 2
        assert open_ports.count("COM15") >= 2
        assert caplog.messages.count("The OSR2 is plugged in on COM4") == 1

    def test_follows_the_osr2_to_whichever_socket_it_is_plugged_into(
        self, broker_app_module, cfg_path,
    ):
        open_ports: list[str] = []
        FakeSerial = make_fake_serial(
            open_ports, fail_once_on=("COM4", broker_app_module.serial.SerialException),
        )
        sockets = iter([["COM4"]])
        slept = {"count": 0}

        def fake_sleep(_seconds):
            slept["count"] += 1
            if "COM5" in open_ports or slept["count"] >= 50:
                raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=fake_sleep,
                           osr2_adapters=lambda: next(sockets, ["COM5"])):
            broker_app_module.main(["--config", str(cfg_path)])

        assert [port for port in open_ports if port != "COM15"] == ["COM4", "COM5"]


class TestMainSurvivesMfpConfigTrouble:
    def test_starts_brokering_when_mfp_config_cannot_be_written(self, broker_app_module, cfg_path):
        open_ports: list[str] = []
        FakeSerial = make_fake_serial(open_ports)

        def fake_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=fake_sleep,
                           mfp_config_error=PermissionError(13, "Access is denied")):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        assert "COM4" in open_ports


class TestMainConfiguredWithoutMfp:
    def test_a_broker_without_an_mfp_config_leaves_mfp_alone(self, broker_app_module, cfg_factory):
        cfg_path = cfg_factory({"mfp_config_path": ""})
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=stop_on_first_sleep):
            broker_app_module.main(["--config", str(cfg_path)])
            broker_app_module.ensure_mfp_serial_port.assert_not_called()


class TestBrokerSingleInstance:
    def test_exits_when_already_running(self, broker_app_module, cfg_path):
        logger = logging.getLogger("test.broker")
        mock_socket_mod = MagicMock()
        with patch.object(broker_app_module, "configure_logging", return_value=logger), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch.object(broker_app_module, "try_acquire_mutex", return_value=None), \
             patch.object(broker_app_module, "socket", mock_socket_mod):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        mock_socket_mod.socket.assert_not_called()


class TestMainSaysWhatKeepsTheOsr2Unheard:
    def test_a_broker_that_cannot_find_the_osr2_says_so_where_every_app_reads_it(
        self, broker_app_module, cfg_path,
    ):
        config = load_config(str(cfg_path))
        sockets = iter([[]])

        def stop_on_the_first_session(_seconds):
            if (config.state_dir / "osr2_not_found.txt").exists():
                raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=make_fake_serial([]),
                           sleep=stop_on_the_first_session,
                           osr2_adapters=lambda: next(sockets, ["COM4"])):
            broker_app_module.main(["--config", str(cfg_path)])

        assert (config.state_dir / "osr2_not_found.txt").exists()

    def test_a_broker_counts_an_unheard_osr2_being_driven_where_every_app_reads_it(
        self, broker_app_module, cfg_path,
    ):
        config = load_config(str(cfg_path))

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with (
            _main_running(broker_app_module, fake_serial=make_fake_serial([]),
                          sleep=stop_on_first_sleep),
            patch.object(broker_app_module, "NotAnsweringWatch") as watch,
        ):
            broker_app_module.main(["--config", str(cfg_path)])

        assert watch.call_args.kwargs["stamp_file"] == config.state_dir / "osr2_not_answering.txt"


class TestMainPublishesItsStateFiles:
    def test_a_started_broker_leaves_the_mode_file_where_the_family_looks(
        self, broker_app_module, cfg_path,
    ):
        config = load_config(str(cfg_path))
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial,
                           sleep=stop_on_first_sleep):
            broker_app_module.main(["--config", str(cfg_path)])

        assert (config.state_dir / "broker_mode.txt").read_text(encoding="utf-8") == "0"

    def test_a_started_broker_says_which_checkout_it_runs_from(self, broker_app_module, cfg_path):
        config = load_config(str(cfg_path))
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial,
                           sleep=stop_on_first_sleep):
            broker_app_module.main(["--config", str(cfg_path)])

        assert config.broker_checkout_file.read_text(encoding="utf-8") == str(PROJECT_DIR)

    def test_a_started_broker_says_in_its_mode_file_that_it_is_under_control(
        self, broker_app_module, cfg_path,
    ):
        config = load_config(str(cfg_path))
        config.state_dir.mkdir(parents=True, exist_ok=True)
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial,
                           sleep=stop_on_first_sleep):
            broker_app_module.main(["--config", str(cfg_path)])

        assert (config.state_dir / "broker_mode.txt").read_text(encoding="utf-8") == "0"


def _stop_on_first_sleep(_seconds):
    raise KeyboardInterrupt


class TestMainHoldsTheOsr2Slot:
    def test_the_session_is_handed_a_slot_that_listens_while_the_broker_runs(
        self, broker_app_module, cfg_path,
    ):
        built: dict = {}
        listening = []

        def record(**kwargs):
            built.update(kwargs)
            return MagicMock()

        def stop_once_seen(_seconds):
            listening.append(built["senders"].slot.address)
            raise KeyboardInterrupt

        with (
            _main_running(broker_app_module, fake_serial=make_fake_serial([]),
                          sleep=stop_once_seen),
            patch.object(broker_app_module, "BrokerSerialSession", side_effect=record),
        ):
            broker_app_module.main(["--config", str(cfg_path)])

        [address] = listening
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as nothing_listens_there:
            nothing_listens_there.bind(address)

    def test_a_broker_whose_slot_cannot_listen_still_bridges_the_osr2(
        self, broker_app_module, cfg_path,
    ):
        open_ports: list[str] = []

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as somebody_else:
            somebody_else.bind(("127.0.0.1", 0))
            somebody_else.listen()
            with (
                _main_running(broker_app_module, fake_serial=make_fake_serial(open_ports),
                              sleep=_stop_on_first_sleep),
                patch.object(broker_app_module, "OSR2_SLOT", somebody_else.getsockname()[1]),
            ):
                broker_app_module.main(["--config", str(cfg_path)])

        assert "COM4" in open_ports


class TestMainWatchesForThePowerOn:
    @staticmethod
    def _watch_main_builds(broker_app_module, cfg_path):
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        built = {}

        def record(**kwargs):
            built.update(kwargs)
            return MagicMock()

        with (
            _main_running(broker_app_module, fake_serial=FakeSerial,
                          sleep=stop_on_first_sleep),
            patch.object(broker_app_module, "BrokerSerialSession", side_effect=record),
        ):
            broker_app_module.main(["--config", str(cfg_path)])
        return built["watches"].power_on

    def test_a_broker_starting_after_a_silence_treats_the_next_line_as_a_power_on(
        self, broker_app_module, cfg_path,
    ):
        config = load_config(str(cfg_path))
        config.osr2_serial_rx_file.write_text("1.0", encoding="utf-8")

        assert self._watch_main_builds(broker_app_module, cfg_path).rx_broke_the_silence() is True

    def test_a_broker_starting_while_the_device_talks_does_not(
        self, broker_app_module, cfg_path,
    ):
        config = load_config(str(cfg_path))
        config.osr2_serial_rx_file.write_text(str(real_time.time()), encoding="utf-8")

        assert self._watch_main_builds(broker_app_module, cfg_path).rx_broke_the_silence() is False
