"""Tests for osr2_broker.app."""
from __future__ import annotations

import importlib
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

@pytest.fixture()
def broker_app_module():
    fake_serial = types.SimpleNamespace(
        Serial=None,
        SerialException=type("FakeSerialException", (Exception,), {}),
    )
    with patch.dict(sys.modules, {"serial": fake_serial}):
        module = importlib.import_module("osr2_broker.app")
        module = importlib.reload(module)
    return module


class TestParseAutoTransition:
    def test_detects_freemode_on(self, broker_app_module):
        assert broker_app_module.parse_auto_transition("freeMode is on!") is True

    def test_detects_auto_mode_on(self, broker_app_module):
        assert broker_app_module.parse_auto_transition("Auto mode is on!") is True

    def test_detects_auto_mode_off(self, broker_app_module):
        assert broker_app_module.parse_auto_transition("Auto mode is off!") is False

    def test_ignores_unrelated_lines(self, broker_app_module):
        assert broker_app_module.parse_auto_transition("StrokeName: Demo, PatternDuration: 2.0") is None


class TestMainReconnect:
    def test_retries_after_retryable_serial_open_failure(self, broker_app_module, cfg_path):
        open_ports: list[str] = []

        class FakeSocket:
            def sendto(self, _data, _addr):
                return None

            def close(self):
                return None

        class FakeSerial:
            def __init__(self, port, _baud, timeout=0.02):
                open_ports.append(port)
                if port == "COM4" and open_ports.count("COM4") == 1:
                    raise broker_app_module.serial.SerialException("Access is denied")
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

        sleep_calls = {"count": 0}

        def fake_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 4:
                raise KeyboardInterrupt

        with patch.object(broker_app_module, "configure_logging", return_value=logging.getLogger("test.broker")), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch("osr2_broker.single_instance.try_acquire_mutex", return_value=42), \
             patch.object(broker_app_module, "resolve_virtual_port", side_effect=lambda _c, port, _l: port), \
             patch.object(broker_app_module, "ensure_mfp_serial_port"), \
             patch.object(broker_app_module.serial, "Serial", side_effect=FakeSerial), \
             patch.object(broker_app_module, "socket") as mock_socket_mod, \
             patch.object(broker_app_module, "_start_monitor"), \
             patch.object(broker_app_module.time, "sleep", side_effect=fake_sleep):
            mock_socket_mod.socket.return_value = FakeSocket()
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_DGRAM = 2
            result = broker_app_module.main(["--config", str(cfg_path), "--serial-retry-delay", "0"])

        assert result == 0
        assert open_ports.count("COM4") >= 2
        assert open_ports.count("COM15") >= 2


class TestBrokerSingleInstance:
    def test_exits_when_already_running(self, broker_app_module, cfg_path):
        logger = logging.getLogger("test.broker")
        mock_socket_mod = MagicMock()
        with patch.object(broker_app_module, "configure_logging", return_value=logger), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch("osr2_broker.single_instance.try_acquire_mutex", return_value=None), \
             patch.object(broker_app_module, "socket", mock_socket_mod):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        mock_socket_mod.socket.assert_not_called()


def test_write_heartbeat_persists_current_timestamp(tmp_path: Path, broker_app_module):
    heartbeat_file = tmp_path / "state" / "broker_heartbeat.txt"
    logger = logging.getLogger("test.broker")

    with patch("osr2_broker.app.time.time", return_value=123.45):
        broker_app_module.write_heartbeat(heartbeat_file, logger)

    assert heartbeat_file.read_text(encoding="utf-8") == "123.45"


def test_heartbeat_loop_skips_write_when_connected_event_is_clear(tmp_path: Path, broker_app_module):
    import threading
    heartbeat_file = tmp_path / "broker_heartbeat.txt"
    stop = threading.Event()
    connected = threading.Event()
    ticks = []

    def fake_sleep(s):
        ticks.append(s)
        if len(ticks) >= 3:
            stop.set()

    logger = logging.getLogger("test.broker")
    broker_app_module.heartbeat_loop(heartbeat_file, stop, logger, sleep=fake_sleep, connected=connected)
    assert not heartbeat_file.exists(), "heartbeat must not be written while disconnected"


def test_heartbeat_loop_writes_when_connected_event_is_set(tmp_path: Path, broker_app_module):
    import threading
    heartbeat_file = tmp_path / "broker_heartbeat.txt"
    stop = threading.Event()
    connected = threading.Event()
    connected.set()
    ticks = []

    def fake_sleep(s):
        ticks.append(s)
        if len(ticks) >= 1:
            stop.set()

    logger = logging.getLogger("test.broker")
    broker_app_module.heartbeat_loop(heartbeat_file, stop, logger, sleep=fake_sleep, connected=connected)
    assert heartbeat_file.exists(), "heartbeat must be written while connected"
